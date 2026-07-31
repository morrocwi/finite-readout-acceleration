"""
Every Layer B audit tested against the SPECIFIC incident shape it is named
after (from araya-webops), verifying it both catches the incident and does
not false-positive on the fixed version of the same code.
"""

import fra


def test_require_guard_catches_the_functions_php_outage_shape():
    unguarded = "<?php\nrequire '/inc/new-feature.php';\n"
    guarded = "<?php\nif (file_exists('/inc/new-feature.php')) {\n    require '/inc/new-feature.php';\n}\n"
    dynamic = "<?php\nrequire get_stylesheet_directory() . '/inc/new-feature.php';\n"

    r1 = fra.require_guard_audit(unguarded)
    r2 = fra.require_guard_audit(guarded)
    r3 = fra.require_guard_audit(dynamic)

    assert any(f.status == "FAIL" for f in r1)
    assert all(f.status == "PASS" for f in r2)
    # the real bug was a DYNAMIC path -- must be reported undecidable, never a false PASS
    assert r3 and all(f.status == "UNDECIDABLE" for f in r3)


def test_atomic_deploy_catches_the_wpforms_lite_mirror_incident():
    incident = fra.atomic_deploy_audit(file_count=340, method="mirror")
    fixed = fra.atomic_deploy_audit(file_count=340, method="atomic_rename")
    single_file = fra.atomic_deploy_audit(file_count=1, method="mirror")

    assert incident.status == "FAIL"
    assert fixed.status == "PASS"
    assert single_file.status == "PASS"  # G8: single-file direct write is still fine


def test_frozen_data_catches_the_certificate_date_bug():
    buggy = """<?php
function render_certificate($post_id) {
    $issued = date('Y-m-d');
    echo "Issued on: " . $issued;
}
"""
    fixed = """<?php
function render_certificate($post_id) {
    $issued_at = get_post_meta($post_id, 'issued_at', true);
    echo "Issued on: " . $issued_at;
}

function create_certificate($post_id) {
    $issued_at = date('Y-m-d');
    update_post_meta($post_id, 'issued_at', $issued_at);
}
"""
    r_buggy = fra.frozen_data_audit(buggy, frozen_fields=["issued_at"])
    r_fixed = fra.frozen_data_audit(fixed, frozen_fields=["issued_at"])
    assert any(f.status == "FAIL" for f in r_buggy)
    assert all(f.status != "FAIL" for f in r_fixed)


def test_php_parse_gate_holds_honestly_when_php_is_unavailable():
    r = fra.php_parse_gate({"functions.php": "<?php echo 'ok'; ?>"})
    # On a host with no php binary this MUST hold, not fabricate a PASS.
    # On a host WITH php, it must actually lint (either PASS or FAIL, never HOLD).
    import shutil
    if shutil.which("php") is None:
        assert all(f.status == "HOLD" for f in r)
    else:
        assert all(f.status in ("PASS", "FAIL") for f in r)


def test_route_smoke_test_catches_what_parse_checking_cannot():
    def broken_route():
        return undefined_helper_function_removed_last_deploy()  # noqa: F821

    def ok_route():
        return 200

    r = fra.route_smoke_test({"/broken": broken_route, "/ok": ok_route})
    assert any(f.status == "FAIL" and "broken" in f.detail for f in r)
    assert any(f.status == "PASS" and "ok" in f.detail for f in r)


def test_metric_staleness_refuses_a_week_old_measurement():
    now = 1_800_000_000.0
    fresh = fra.MeasuredValue(value=1.34, measured_at=now - 60, source="c_f", max_age_seconds=3600)
    stale = fra.MeasuredValue(value=1.34, measured_at=now - 7 * 86400, source="c_f", max_age_seconds=3600)
    assert fra.metric_staleness_check(fresh, now).status == "PASS"
    assert fra.metric_staleness_check(stale, now).status == "FAIL"


def test_silent_zero_collapse_catches_common_shapes_and_respects_the_escape_hatch():
    buggy_php = '<?php $v = $row["reading"] ?? 0; echo $v;'
    buggy_sql = "SELECT COALESCE(sensor_value, 0) FROM readings;"
    buggy_js = "const t = data.temperature || 0;"
    annotated = (
        "<?php\n"
        "// collapse-ok: business rule says missing discount defaults to 0, confirmed with finance\n"
        '$discount = $row["discount"] ?? 0;\n'
    )
    clean = "<?php $x = $a + $b; echo $x;"

    assert fra.silent_zero_collapse_audit(buggy_php)
    assert fra.silent_zero_collapse_audit(buggy_sql)
    assert fra.silent_zero_collapse_audit(buggy_js)
    assert not fra.silent_zero_collapse_audit(annotated)
    assert not fra.silent_zero_collapse_audit(clean)
