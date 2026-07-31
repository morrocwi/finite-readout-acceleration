<?php
/**
 * ARAYA Readout Cache — Finite Readout Acceleration for WordPress.
 *
 * NOT DEPLOYED. This is a reviewable artifact only; live deploy on
 * arayaweddingplanner.com goes through the araya-webops gate (maintenance window,
 * REST/wp-admin, independent review) and is never bulk-FTP'd.
 *
 * What this is: the paper's criterion (Lahtee 2026) made operational, with the three
 * gaps the review found closed:
 *
 *   G2  the error/consistency claim is measured by WORST case, never by average;
 *   G3  K_N/N is monitored ONLINE and the quotient self-disables when it stops
 *       paying, instead of silently becoming a slowdown after a traffic shift;
 *   S   the key-safety audit (ker Q subseteq ker g) runs in SHADOW MODE on live
 *       traffic, so an unsafe key is caught by data rather than by opinion.
 *
 * The security rule this enforces, from Section 10.1 and confirmed by experiment E4:
 * a faster key that merges two permission classes is not an optimisation, it is a
 * data-leak. Every attribute that can change authorised output MUST be in the key.
 *
 * @package ARAYA
 */

defined( 'ABSPATH' ) || exit;

class ARAYA_Readout_Cache {

	/** Bump when the quotient definition changes — old entries must not be reused. */
	const QUOTIENT_VERSION = 'q1';

	/** Sliding-window size for the online break-even monitor. */
	const WINDOW = 500;

	/**
	 * Cost model, in microseconds, for the work this cache is protecting.
	 * Measure these on the real host; do not inherit someone else's numbers.
	 *
	 * @var array{c_f:float,c_o:float,c_m:float}
	 */
	private $cost;

	/** @var string */
	private $group;

	/** @var bool Shadow-mode key-safety auditing. */
	private $audit;

	public function __construct( $group, array $cost, $audit = false ) {
		$this->group = $group;
		$this->cost  = wp_parse_args( $cost, array( 'c_f' => 2000.0, 'c_o' => 5.0, 'c_m' => 0.0 ) );
		$this->audit = (bool) $audit;
	}

	/**
	 * Break-even distinct-key ratio: the quotient pays only while K_N/N is below this.
	 *
	 * Theorem 3: K_N/N < (c_f - c_o) / (c_f + c_m).
	 */
	public function break_even_alpha() {
		$c_f = (float) $this->cost['c_f'];
		$c_o = (float) $this->cost['c_o'];
		$c_m = (float) $this->cost['c_m'];
		if ( $c_f <= $c_o ) {
			return 0.0; // No collapse rate can ever pay. Do not cache this.
		}
		return ( $c_f - $c_o ) / ( $c_f + $c_m );
	}

	/**
	 * The readout key.
	 *
	 * EVERY attribute that can change authorised or user-visible output belongs here.
	 * Experiment E4 measured the temptation precisely: dropping the role from the key
	 * was the FASTEST option in the table (2.85x vs 2.27x) and served a logged-out
	 * visitor's gated page to a member from one entry.
	 *
	 * @param array $ctx Request context.
	 * @return string
	 */
	public function key( array $ctx ) {
		$parts = array(
			'v'    => self::QUOTIENT_VERSION,
			'g'    => $this->group,
			// --- authorisation-affecting: NEVER remove any of these ---
			'role' => $this->role_class(),
			'lang' => isset( $ctx['lang'] ) ? $ctx['lang'] : 'th',
			// --- content-affecting ---
			'prov' => isset( $ctx['province'] ) ? $ctx['province'] : '',
			'svc'  => isset( $ctx['service'] ) ? $ctx['service'] : '',
			// --- quotiented: the readout does not retain finer time than one day ---
			'day'  => isset( $ctx['ts'] ) ? (int) floor( $ctx['ts'] / DAY_IN_SECONDS ) : 0,
			// --- invalidation coordinates (Section 10.3) ---
			'dv'   => $this->data_version(),
			'pv'   => $this->policy_version(),
		);
		return 'araya_fra_' . md5( wp_json_encode( $parts ) );
	}

	/**
	 * Permission CLASS, not user id. Merging inside a class is the whole point;
	 * merging across classes is the bug.
	 */
	private function role_class() {
		if ( ! is_user_logged_in() ) {
			return 'guest';
		}
		if ( current_user_can( 'manage_options' ) ) {
			return 'admin';
		}
		if ( current_user_can( 'edit_posts' ) ) {
			return 'editor';
		}
		return 'member';
	}

	private function data_version() {
		return (string) get_option( 'araya_fra_data_version', '1' );
	}

	private function policy_version() {
		return (string) get_option( 'araya_fra_policy_version', '1' );
	}

	/**
	 * The Listing-1 execution pattern: key -> hit? -> compute representative -> store.
	 *
	 * @param array    $ctx      Request context.
	 * @param callable $expensive Produces the readout for this context.
	 * @return mixed
	 */
	public function get( array $ctx, callable $expensive ) {
		if ( ! $this->enabled() ) {
			return call_user_func( $expensive, $ctx );
		}

		$k     = $this->key( $ctx );
		$found = false;
		$value = wp_cache_get( $k, $this->group, false, $found );

		if ( false === $found ) {
			$value = call_user_func( $expensive, $ctx );
			wp_cache_set( $k, $value, $this->group, $this->ttl() );
		}

		$this->observe( $k, (bool) $found );

		if ( $this->audit ) {
			$this->audit_key( $k, $value );
		}

		return $value;
	}

	private function ttl() {
		return 10 * MINUTE_IN_SECONDS;
	}

	// ------------------------------------------------------------------
	// G3 — online break-even monitor
	// ------------------------------------------------------------------

	/**
	 * Record one request and re-evaluate whether the quotient is still paying.
	 *
	 * K_N/N is a readout of the prefix already served. It does not bound the traffic
	 * about to arrive. Experiment E6: an unmonitored deployment that drifts from a
	 * repetitive trace to a near-unique one turns a win into a modelled 0.90x LOSS
	 * with nothing to announce it; the guard recovers it to 1.19x by falling back.
	 */
	private function observe( $key, $was_hit ) {
		$state = get_transient( $this->state_key() );
		if ( ! is_array( $state ) ) {
			$state = array( 'n' => 0, 'keys' => array(), 'off' => false );
		}

		$state['n']++;
		$state['keys'][ $key ] = 1;

		if ( $state['n'] >= self::WINDOW ) {
			$alpha = count( $state['keys'] ) / $state['n'];
			$limit = 0.9 * $this->break_even_alpha();   // hysteresis margin

			if ( ! $state['off'] && $alpha > $limit ) {
				$state['off'] = true;
				$this->log( sprintf(
					'quotient DISABLED: alpha=%.3f exceeded %.3f (break-even %.3f)',
					$alpha,
					$limit,
					$this->break_even_alpha()
				) );
			} elseif ( $state['off'] && $alpha < 0.5 * $limit ) {
				$state['off'] = false;
				$this->log( sprintf( 'quotient re-enabled: alpha=%.3f', $alpha ) );
			}
			$state['n']    = 0;
			$state['keys'] = array();
		}

		set_transient( $this->state_key(), $state, HOUR_IN_SECONDS );
	}

	public function enabled() {
		if ( $this->break_even_alpha() <= 0.0 ) {
			return false; // c_f <= c_o: caching this can only ever be slower.
		}
		$state = get_transient( $this->state_key() );
		return ! ( is_array( $state ) && ! empty( $state['off'] ) );
	}

	private function state_key() {
		return 'araya_fra_state_' . $this->group;
	}

	// ------------------------------------------------------------------
	// S — shadow-mode key-safety audit  (Definition 1 as a live linter)
	// ------------------------------------------------------------------

	/**
	 * Store a fingerprint of the readout per key. If the SAME key ever produces a
	 * DIFFERENT readout, ker(Q) is not contained in ker(g) and the key is unsafe —
	 * on real traffic, not on an argument. Run this for a week before trusting a
	 * new key design; it costs one hash per request and never changes behaviour.
	 */
	private function audit_key( $key, $value ) {
		$fingerprint = md5( maybe_serialize( $value ) );
		$seen        = get_transient( 'araya_fra_audit_' . $key );

		if ( false === $seen ) {
			set_transient( 'araya_fra_audit_' . $key, $fingerprint, DAY_IN_SECONDS );
			return;
		}
		if ( $seen !== $fingerprint ) {
			$this->log( sprintf(
				'KEY UNSAFE: key %s produced two different readouts (%s vs %s) — '
					. 'the key is missing an attribute that changes output',
				$key,
				$seen,
				$fingerprint
			) );
		}
	}

	private function log( $message ) {
		if ( defined( 'WP_DEBUG' ) && WP_DEBUG ) {
			error_log( '[araya-fra][' . $this->group . '] ' . $message ); // phpcs:ignore
		}
		do_action( 'araya_fra_event', $this->group, $message );
	}
}
