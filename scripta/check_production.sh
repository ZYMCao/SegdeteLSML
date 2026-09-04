#!/usr/bin/env bash
# check_production.sh — read-only production verification for SegDete.
#
# Runs on the production box inside the /opt/segdete worktree, AFTER `git pull`.
# Read-only: it never modifies the venv, services, unit files, devices, or nginx.
# It verifies repository/venv/config convergence plus live service, HTTP, MQTT,
# filesystem, disk, timer, device-inventory, and fatal-log health.
#
# Design rules:
#   - Environment= entries are compared by KEY only, never by value, and
#     values are never printed (tokens stay secret).
#   - Exit codes: 0 = all green, 1 = action needed (exact fix commands are
#     printed), 2 = the script itself cannot run (fail loud).
#   - Portable bash (macOS bash 3.2 and Linux): no associative arrays, no
#     mapfile, no process substitution in critical paths.
#
# Tunables (env overrides exist so the script is testable with fixtures):
#   REPO_ROOT, SYSTEMD_DIR, NGINX_AVAILABLE, NGINX_ENABLED, UDEV_DIR,
#   STRICT_LIVE=1 (set 0 to skip all host-runtime checks when testing),
#   UV_BIN, CHECK_RELEASE=1, EXPECTED_BRANCH=quinque, EXPECTED_COMMIT,
#   TB_EDGE_URL, NGINX_URL, STATIC_URL, MQTT_PORT=1883,
#   MIN_DISK_FREE_KB=1048576, MAX_UNIT_RESTARTS=0,
#   HARDWARE_PROFILE=report (report|none|buzzer-geo|camera|all),
#   EXPECTED_BASLER_COUNT, EXPECTED_BUZZER_COUNT,
#   EXPECTED_GEOPOSITION_COUNT, EXPECTED_CAMERA_SNS.

set -uo pipefail

EXIT=0
ACTIONS=0

# ---------------------------------------------------------------- locations
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd)}"
BACKEND_DIR="$REPO_ROOT/backend"
DEPLOY_DIR="$REPO_ROOT/deploy"
SYSTEMD_DIR="${SYSTEMD_DIR:-/etc/systemd/system}"
NGINX_AVAILABLE="${NGINX_AVAILABLE:-/etc/nginx/sites-available/segdete}"
NGINX_ENABLED="${NGINX_ENABLED:-/etc/nginx/sites-enabled/segdete}"
UDEV_DIR="${UDEV_DIR:-/etc/udev/rules.d}"
STRICT_LIVE="${STRICT_LIVE:-1}"
UV_BIN="${UV_BIN:-}"
CHECK_RELEASE="${CHECK_RELEASE:-1}"
EXPECTED_BRANCH="${EXPECTED_BRANCH:-quinque}"
EXPECTED_COMMIT="${EXPECTED_COMMIT:-}"
TB_EDGE_URL="${TB_EDGE_URL:-http://127.0.0.1:8080/}"
NGINX_URL="${NGINX_URL:-http://127.0.0.1/}"
STATIC_URL="${STATIC_URL:-http://127.0.0.1/static-persister/segdete/}"
MQTT_PORT="${MQTT_PORT:-1883}"
MIN_DISK_FREE_KB="${MIN_DISK_FREE_KB:-1048576}"
MAX_UNIT_RESTARTS="${MAX_UNIT_RESTARTS:-0}"
HARDWARE_PROFILE="${HARDWARE_PROFILE:-report}"
EXPECTED_BASLER_COUNT="${EXPECTED_BASLER_COUNT:-}"
EXPECTED_BUZZER_COUNT="${EXPECTED_BUZZER_COUNT:-}"
EXPECTED_GEOPOSITION_COUNT="${EXPECTED_GEOPOSITION_COUNT:-}"
EXPECTED_CAMERA_SNS="${EXPECTED_CAMERA_SNS:-}"

case "$HARDWARE_PROFILE" in
    report) ;;
    none)
        [ -n "$EXPECTED_BASLER_COUNT" ] || EXPECTED_BASLER_COUNT=0
        [ -n "$EXPECTED_BUZZER_COUNT" ] || EXPECTED_BUZZER_COUNT=0
        [ -n "$EXPECTED_GEOPOSITION_COUNT" ] || EXPECTED_GEOPOSITION_COUNT=0
        ;;
    buzzer-geo)
        [ -n "$EXPECTED_BASLER_COUNT" ] || EXPECTED_BASLER_COUNT=0
        [ -n "$EXPECTED_BUZZER_COUNT" ] || EXPECTED_BUZZER_COUNT=1
        [ -n "$EXPECTED_GEOPOSITION_COUNT" ] || EXPECTED_GEOPOSITION_COUNT=1
        ;;
    camera)
        [ -n "$EXPECTED_BASLER_COUNT" ] || EXPECTED_BASLER_COUNT=2
        [ -n "$EXPECTED_BUZZER_COUNT" ] || EXPECTED_BUZZER_COUNT=0
        [ -n "$EXPECTED_GEOPOSITION_COUNT" ] || EXPECTED_GEOPOSITION_COUNT=0
        ;;
    all)
        [ -n "$EXPECTED_BASLER_COUNT" ] || EXPECTED_BASLER_COUNT=2
        [ -n "$EXPECTED_BUZZER_COUNT" ] || EXPECTED_BUZZER_COUNT=1
        [ -n "$EXPECTED_GEOPOSITION_COUNT" ] || EXPECTED_GEOPOSITION_COUNT=1
        ;;
    *)
        printf '[ERROR]  HARDWARE_PROFILE must be report, none, buzzer-geo, camera, or all\n' >&2
        exit 2
        ;;
esac

UNITS="segdete buzzer geoposition segdete-cleanup"
TIMERS="segdete-cleanup"
RUNNING_UNITS="tb-edge segdete buzzer geoposition nginx"
STRUCT_KEYS="User Group WorkingDirectory ExecStart Restart RestartSec Type StandardOutput StandardError KillSignal TimeoutStopSec"

# ---------------------------------------------------------------- reporting
ok()     { printf '[OK]     %s\n' "$1"; }
action() { printf '[ACTION] %s\n' "$1"; ACTIONS=$((ACTIONS + 1)); EXIT=1; }
skip()   { printf '[SKIP]   %s\n' "$1"; }
die()    { printf '[ERROR]  %s\n' "$1" >&2; exit 2; }

# ---------------------------------------------------------------- parsing
# Print sorted unique Environment= KEY names from a unit file. Values are
# dropped before they can leak; fragments that are not valid identifiers
# (e.g. continuations of quoted values with spaces) are filtered out.
env_keys_of_file() {
    grep -E '^[[:space:]]*Environment=' "$1" 2>/dev/null \
        | sed -E 's/^[[:space:]]*Environment=//' \
        | tr ' ' '\n' \
        | sed -E 's/^"//; s/"$//' \
        | cut -d= -f1 \
        | grep -E '^[A-Za-z_][A-Za-z0-9_]*$' \
        | sort -u
}

# Same, but from `systemctl show --value` output on stdin.
env_keys_of_text() {
    tr ' ' '\n' \
        | sed -E 's/^"//; s/"$//' \
        | cut -d= -f1 \
        | grep -E '^[A-Za-z_][A-Za-z0-9_]*$' \
        | sort -u
}

# First occurrence of a structural directive's full value (no secrets here).
struct_of_file() {
    sed -n -E "s/^[[:space:]]*$2=//p" "$1" 2>/dev/null | head -n 1
}

env_value_of_file() {
    sed -n -E "s/^[[:space:]]*Environment=\"?$2=([^\"]*)\"?$/\\1/p" "$1" 2>/dev/null | head -n 1
}

resolve_uv() {
    [ -n "$UV_BIN" ] && [ -x "$UV_BIN" ] && return
    UV_BIN="$(command -v uv 2>/dev/null || true)"
    [ -n "$UV_BIN" ] && return
    [ -x /root/.cargo/bin/uv ] && UV_BIN=/root/.cargo/bin/uv
}

# ---------------------------------------------------------------- part 0: release
check_release() {
    printf -- '--- 0. release identity ---\n'
    git -C "$REPO_ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1 \
        || die "$REPO_ROOT is not a git worktree"

    branch="$(git -C "$REPO_ROOT" symbolic-ref --quiet --short HEAD 2>/dev/null || true)"
    if [ "$branch" = "$EXPECTED_BRANCH" ]; then
        ok "branch: $branch"
    else
        action "WRONG_BRANCH: <$branch> (want <$EXPECTED_BRANCH>)"
    fi

    dirty="$(git -C "$REPO_ROOT" status --porcelain 2>/dev/null)"
    if [ -z "$dirty" ]; then
        ok "worktree is clean"
    else
        action "DIRTY_WORKTREE: uncommitted paths exist"
        printf '%s\n' "$dirty" | sed 's/^/         /'
    fi

    head_commit="$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null)" \
        || die "cannot resolve HEAD under $REPO_ROOT"
    if [ -n "$EXPECTED_COMMIT" ]; then
        expected="$(git -C "$REPO_ROOT" rev-parse "$EXPECTED_COMMIT^{commit}" 2>/dev/null)" \
            || die "cannot resolve EXPECTED_COMMIT=$EXPECTED_COMMIT"
        if [ "$head_commit" = "$expected" ]; then
            ok "HEAD matches EXPECTED_COMMIT: $head_commit"
        else
            action "WRONG_COMMIT: HEAD=$head_commit want=$expected"
        fi
        return
    fi

    upstream="$(git -C "$REPO_ROOT" rev-parse --abbrev-ref '@{upstream}' 2>/dev/null || true)"
    if [ -z "$upstream" ]; then
        action "NO_UPSTREAM: set EXPECTED_COMMIT or configure a tracking branch"
        return
    fi
    upstream_commit="$(git -C "$REPO_ROOT" rev-parse "$upstream" 2>/dev/null || true)"
    if [ "$head_commit" = "$upstream_commit" ]; then
        ok "HEAD matches local tracking ref $upstream: $head_commit"
    else
        action "REVISION_DRIFT: HEAD=$head_commit $upstream=$upstream_commit"
    fi
    skip "EXPECTED_COMMIT not set; remote freshness was not checked"
}

# ---------------------------------------------------------------- part 1: venv
check_venv() {
    printf -- '--- 1. venv sync (backend/) ---\n'
    [ -d "$BACKEND_DIR" ] || die "backend/ not found under $REPO_ROOT"
    resolve_uv
    [ -n "$UV_BIN" ] || die "uv not found; set UV_BIN or install uv"
    if ( cd "$BACKEND_DIR" && "$UV_BIN" lock --check >/dev/null 2>&1 ); then
        ok "uv.lock is consistent with backend/pyproject.toml"
    else
        action "REPO_INCONSISTENT: uv.lock does not match backend/pyproject.toml — re-lock on dev machine, commit, pull again"
        return
    fi
    if ( cd "$BACKEND_DIR" && "$UV_BIN" sync --frozen --check >/dev/null 2>&1 ); then
        ok "backend/.venv is in sync (no uv sync needed)"
    else
        action "NEEDS_SYNC: run: cd $BACKEND_DIR && uv sync --frozen"
        printf '         then restart all services sharing the venv: sudo systemctl restart segdete buzzer geoposition\n'
    fi
}

# ---------------------------------------------------------------- part 2: units
check_unit_files() {
    unit="$1"
    repo="$DEPLOY_DIR/$unit.service"
    inst="$SYSTEMD_DIR/$unit.service"
    [ -f "$repo" ] || die "repo unit missing: $repo"
    if [ ! -f "$inst" ]; then
        action "UNIT_NOT_INSTALLED: $unit (missing $inst)"
        printf '         fix: sudo cp %s %s && sudo systemctl daemon-reload && sudo systemctl restart %s\n' "$repo" "$inst" "$unit"
        return
    fi
    drift=0
    for key in $STRUCT_KEYS; do
        a="$(struct_of_file "$repo" "$key")"
        b="$(struct_of_file "$inst" "$key")"
        if [ "$a" != "$b" ]; then
            action "FILE_DRIFT: $unit [$key] repo=<$a> installed=<$b>"
            drift=1
        fi
    done
    missing="$(comm -23 <(env_keys_of_file "$repo") <(env_keys_of_file "$inst"))"
    extra="$(comm -13 <(env_keys_of_file "$repo") <(env_keys_of_file "$inst"))"
    [ -n "$missing" ] && { action "FILE_DRIFT: $unit env keys missing in installed file:"; printf '%s\n' "$missing" | sed 's/^/         - /'; drift=1; }
    [ -n "$extra" ] && { action "FILE_DRIFT: $unit extra env keys in installed file:"; printf '%s\n' "$extra" | sed 's/^/         + /'; drift=1; }
    if [ "$drift" -eq 1 ]; then
        printf '         fix: sudo cp %s %s && sudo systemctl daemon-reload && sudo systemctl restart %s\n' "$repo" "$inst" "$unit"
    else
        ok "$unit: repo == installed (structure + env keys)"
    fi
}

check_unit_live() {
    unit="$1"
    if [ "$STRICT_LIVE" -eq 0 ]; then
        skip "$unit: live systemd check disabled (STRICT_LIVE=0)"
        return
    fi
    if ! command -v systemctl >/dev/null 2>&1; then
        [ "$STRICT_LIVE" -eq 1 ] && die "systemctl not found; live check impossible"
        skip "$unit: no systemctl, live check skipped"
        return
    fi
    inst="$SYSTEMD_DIR/$unit.service"
    [ -f "$inst" ] || return
    load="$(systemctl show "$unit" -p LoadState --value 2>/dev/null)"
    if [ "$load" != "loaded" ]; then
        action "UNIT_NOT_LOADED: $unit (LoadState=<$load>) — fix: sudo systemctl daemon-reload && sudo systemctl restart $unit"
        return
    fi
    live_keys="$(systemctl show "$unit" -p Environment --value 2>/dev/null | env_keys_of_text)"
    repo_tmp="$(mktemp)"; inst_tmp="$(mktemp)"
    env_keys_of_file "$inst" >"$repo_tmp"
    printf '%s\n' "$live_keys" >"$inst_tmp"
    missing="$(comm -23 "$repo_tmp" "$inst_tmp")"
    extra="$(comm -13 "$repo_tmp" "$inst_tmp")"
    rm -f "$repo_tmp" "$inst_tmp"
    if [ -n "$missing" ] || [ -n "$extra" ]; then
        [ -n "$missing" ] && { action "RELOAD_NEEDED: $unit live env missing keys:"; printf '%s\n' "$missing" | sed 's/^/         - /'; }
        [ -n "$extra" ] && { action "RELOAD_NEEDED: $unit live env has extra keys:"; printf '%s\n' "$extra" | sed 's/^/         + /'; }
        printf '         fix: sudo systemctl daemon-reload && sudo systemctl restart %s\n' "$unit"
    else
        ok "$unit: live env keys match installed file"
    fi
}

check_running_unit() {
    unit="$1"
    active="$(systemctl show "$unit" -p ActiveState --value 2>/dev/null)"
    sub="$(systemctl show "$unit" -p SubState --value 2>/dev/null)"
    pid="$(systemctl show "$unit" -p MainPID --value 2>/dev/null)"
    if [ "$active" != "active" ] || [ -z "$pid" ] || [ "$pid" = "0" ]; then
        action "UNIT_NOT_RUNNING: $unit (ActiveState=<$active> SubState=<$sub> MainPID=<$pid>)"
        printf '         inspect: sudo systemctl status %s --no-pager\n' "$unit"
        printf '         fix: sudo systemctl restart %s\n' "$unit"
        return
    fi
    ok "$unit: active/$sub (MainPID=$pid)"

    case " $UNITS " in
        *" $unit "*)
            repo="$DEPLOY_DIR/$unit.service"
            expected_exec="$(struct_of_file "$repo" ExecStart)"
            actual_exec="$(ps -p "$pid" -o args= 2>/dev/null || true)"
            if [ -n "$expected_exec" ] && printf '%s\n' "$actual_exec" | grep -F "$expected_exec" >/dev/null 2>&1; then
                ok "$unit: MainPID command contains repo ExecStart"
            else
                action "EXECSTART_MISMATCH: $unit MainPID command does not contain <$expected_exec>"
            fi
            ;;
    esac

    case "$unit" in
        segdete|buzzer|geoposition)
            restarts="$(systemctl show "$unit" -p NRestarts --value 2>/dev/null)"
            case "$restarts" in
                ''|*[!0-9]*) action "RESTART_COUNT_UNKNOWN: $unit NRestarts=<$restarts>" ;;
                *)
                    if [ "$restarts" -le "$MAX_UNIT_RESTARTS" ]; then
                        ok "$unit: NRestarts=$restarts (max $MAX_UNIT_RESTARTS)"
                    else
                        action "RESTART_LOOP: $unit NRestarts=$restarts exceeds $MAX_UNIT_RESTARTS"
                    fi
                    ;;
            esac
            ;;
    esac
}

check_runtime_units() {
    printf -- '--- 2c. active services and failed units ---\n'
    if [ "$STRICT_LIVE" -eq 0 ]; then
        skip "runtime unit checks disabled (STRICT_LIVE=0)"
        return
    fi
    if ! command -v systemctl >/dev/null 2>&1; then
        [ "$STRICT_LIVE" -eq 1 ] && die "systemctl not found; runtime checks impossible"
        skip "runtime unit checks: no systemctl"
        return
    fi
    for unit in $RUNNING_UNITS; do
        check_running_unit "$unit"
    done
    failed="$(systemctl --failed --no-legend --plain 2>/dev/null | sed '/^[[:space:]]*$/d')"
    if [ -z "$failed" ]; then
        ok "systemd: no failed units"
    else
        action "SYSTEMD_FAILED_UNITS:"
        printf '%s\n' "$failed" | sed 's/^/         /'
    fi
}

check_timer() {
    name="$1"
    repo="$DEPLOY_DIR/$name.timer"
    inst="$SYSTEMD_DIR/$name.timer"
    [ -f "$repo" ] || die "repo timer missing: $repo"
    if [ ! -f "$inst" ]; then
        action "TIMER_NOT_INSTALLED: $name"
        printf '         fix: sudo cp %s %s && sudo systemctl daemon-reload && sudo systemctl enable --now %s.timer\n' "$repo" "$inst" "$name"
        return
    fi
    if cmp -s "$repo" "$inst"; then
        ok "$name.timer: repo == installed"
    else
        action "TIMER_DRIFT: $name.timer differs"
        printf '         fix: sudo cp %s %s && sudo systemctl daemon-reload && sudo systemctl restart %s.timer\n' "$repo" "$inst" "$name"
    fi
    if [ "$STRICT_LIVE" -eq 0 ]; then
        skip "$name.timer: live checks disabled (STRICT_LIVE=0)"
        return
    fi
    if command -v systemctl >/dev/null 2>&1; then
        if systemctl is-enabled "$name.timer" >/dev/null 2>&1; then
            ok "$name.timer: enabled"
        else
            action "TIMER_NOT_ENABLED: $name.timer — fix: sudo systemctl enable --now $name.timer"
        fi
        active="$(systemctl show "$name.timer" -p ActiveState --value 2>/dev/null)"
        sub="$(systemctl show "$name.timer" -p SubState --value 2>/dev/null)"
        if [ "$active" = "active" ]; then
            ok "$name.timer: active/$sub"
        else
            action "TIMER_NOT_ACTIVE: $name (ActiveState=<$active> SubState=<$sub>)"
        fi
        next="$(systemctl show "$name.timer" -p NextElapseUSecRealtime --value 2>/dev/null)"
        if [ -n "$next" ] && [ "$next" != "n/a" ]; then
            ok "$name.timer: next run $next"
        else
            action "TIMER_NO_NEXT_RUN: $name"
        fi
    elif [ "$STRICT_LIVE" -eq 1 ]; then
        die "systemctl not found; live check impossible"
    else
        skip "$name.timer: no systemctl, enablement check skipped"
    fi
}

# ---------------------------------------------------------------- part 3: nginx
check_nginx() {
    printf -- '--- 3. nginx ---\n'
    repo="$DEPLOY_DIR/segdete"
    [ -f "$repo" ] || die "repo nginx conf missing: $repo"
    if [ ! -f "$NGINX_AVAILABLE" ] && [ ! -L "$NGINX_AVAILABLE" ]; then
        action "NGINX_FILE_MISSING: $NGINX_AVAILABLE absent"
        printf '         fix: sudo cp %s %s && sudo nginx -t && sudo systemctl reload nginx\n' "$repo" "$NGINX_AVAILABLE"
    elif cmp -s "$repo" "$NGINX_AVAILABLE"; then
        ok "nginx: repo == $NGINX_AVAILABLE"
    else
        action "NGINX_FILE_DRIFT: $NGINX_AVAILABLE differs from repo"
        printf '         fix: sudo cp %s %s && sudo nginx -t && sudo systemctl reload nginx\n' "$repo" "$NGINX_AVAILABLE"
    fi
    if [ ! -e "$NGINX_ENABLED" ] && [ ! -L "$NGINX_ENABLED" ]; then
        action "NGINX_LINK_MISSING: $NGINX_ENABLED absent"
        printf '         fix: sudo ln -s ../sites-available/segdete %s && sudo nginx -t && sudo systemctl reload nginx\n' "$NGINX_ENABLED"
    elif [ ! -L "$NGINX_ENABLED" ]; then
        action "NGINX_LINK_NOT_SYMLINK: $NGINX_ENABLED exists but is not a symlink (edits to sites-available will silently stop applying)"
        printf '         fix: sudo rm %s && sudo ln -s ../sites-available/segdete %s && sudo nginx -t && sudo systemctl reload nginx\n' "$NGINX_ENABLED" "$NGINX_ENABLED"
    else
        target="$(readlink -f "$NGINX_ENABLED" 2>/dev/null || readlink "$NGINX_ENABLED")"
        want="$(readlink -f "$NGINX_AVAILABLE" 2>/dev/null || printf '%s' "$NGINX_AVAILABLE")"
        if [ "$target" = "$want" ]; then
            ok "nginx: $NGINX_ENABLED -> $target"
        else
            action "NGINX_LINK_WRONG_TARGET: $NGINX_ENABLED -> <$target> (want <$want>; dangling links land here too)"
            printf '         fix: sudo ln -sfn ../sites-available/segdete %s && sudo nginx -t && sudo systemctl reload nginx\n' "$NGINX_ENABLED"
        fi
    fi

    if [ "$STRICT_LIVE" -eq 0 ]; then
        skip "nginx syntax and HTTP checks disabled (STRICT_LIVE=0)"
        return
    fi
    command -v nginx >/dev/null 2>&1 || die "nginx command not found"
    if nginx -t -q >/dev/null 2>&1; then
        ok "nginx: syntax valid"
    else
        action "NGINX_CONFIG_INVALID: nginx -t failed"
    fi
}

# ---------------------------------------------------------------- part 4: udev
check_udev() {
    printf -- '--- 4. udev rules ---\n'
    repo="$DEPLOY_DIR/69-basler-cameras.rules"
    inst="$UDEV_DIR/69-basler-cameras.rules"
    [ -f "$repo" ] || die "repo udev rules missing: $repo"
    if [ ! -f "$inst" ]; then
        action "UDEV_MISSING: $inst absent"
        printf '         fix: sudo cp %s %s && sudo udevadm control --reload-rules && sudo udevadm trigger\n' "$repo" "$inst"
    elif cmp -s "$repo" "$inst"; then
        ok "udev: repo == $inst"
    else
        action "UDEV_DRIFT: $inst differs from repo"
        printf '         fix: sudo cp %s %s && sudo udevadm control --reload-rules && sudo udevadm trigger\n' "$repo" "$inst"
    fi
}

# ---------------------------------------------------------------- part 5: endpoints and MQTT
check_http() {
    label="$1"
    url="$2"
    result="$(curl -fsS --connect-timeout 3 --max-time 10 \
        -o /dev/null -w '%{http_code} %{content_type}' "$url" 2>/dev/null)"
    rc=$?
    code="${result%% *}"
    if [ "$rc" -eq 0 ] && [ "$code" = "200" ]; then
        ok "$label: HTTP $result"
    else
        action "$label: request failed (url=<$url> result=<$result> exit=$rc)"
    fi
}

check_endpoints() {
    printf -- '--- 5. HTTP and MQTT ---\n'
    if [ "$STRICT_LIVE" -eq 0 ]; then
        skip "HTTP and MQTT checks disabled (STRICT_LIVE=0)"
        return
    fi
    command -v curl >/dev/null 2>&1 || die "curl not found"
    command -v ss >/dev/null 2>&1 || die "ss not found"

    check_http "TB Edge" "$TB_EDGE_URL"
    check_http "nginx" "$NGINX_URL"
    check_http "static files" "$STATIC_URL"

    listeners="$(ss -ltn 2>/dev/null | grep -E ":$MQTT_PORT[[:space:]]" || true)"
    if [ -n "$listeners" ]; then
        ok "MQTT: port $MQTT_PORT is listening"
    else
        action "MQTT_NOT_LISTENING: no TCP listener on port $MQTT_PORT"
    fi

    pid="$(systemctl show segdete -p MainPID --value 2>/dev/null)"
    connection=""
    if [ -z "$pid" ] || [ "$pid" = "0" ]; then
        skip "segdete MQTT connection: service is not running (already reported)"
        return
    fi
    connection="$(ss -ntp 2>/dev/null \
        | grep ESTAB \
        | grep -E ":$MQTT_PORT[[:space:]]" \
        | grep "pid=$pid," || true)"
    if [ -n "$connection" ]; then
        ok "segdete: established MQTT connection on port $MQTT_PORT"
    else
        action "SEGDETE_MQTT_DISCONNECTED: MainPID=<$pid> has no established connection on port $MQTT_PORT"
    fi
}

# ---------------------------------------------------------------- part 6: storage and disk
check_access_as_user() {
    user="$1"
    path="$2"
    if [ ! -d "$path" ]; then
        action "DIRECTORY_MISSING: $path"
        return
    fi
    if [ "$(id -u)" -eq 0 ]; then
        command -v runuser >/dev/null 2>&1 || die "runuser not found"
        if runuser -u "$user" -- test -r "$path" \
            && runuser -u "$user" -- test -w "$path" \
            && runuser -u "$user" -- test -x "$path"; then
            ok "$path: readable/writable/searchable by $user"
        else
            action "DIRECTORY_PERMISSION: $user lacks read/write/search access to $path"
        fi
    elif [ "$(id -un)" = "$user" ] && [ -r "$path" ] && [ -w "$path" ] && [ -x "$path" ]; then
        ok "$path: readable/writable/searchable by $user"
    else
        action "DIRECTORY_PERMISSION_UNVERIFIED: run as root or $user to check $path"
    fi
}

check_disk() {
    path="$1"
    available="$(df -Pk "$path" 2>/dev/null | awk 'NR == 2 {print $4}')"
    case "$available" in
        ''|*[!0-9]*) action "DISK_UNKNOWN: cannot read available space for $path" ;;
        *)
            if [ "$available" -ge "$MIN_DISK_FREE_KB" ]; then
                ok "$path: ${available} KiB free (minimum $MIN_DISK_FREE_KB)"
            else
                action "DISK_LOW: $path has ${available} KiB free; minimum is $MIN_DISK_FREE_KB"
            fi
            ;;
    esac
}

check_storage() {
    printf -- '--- 6. storage and logs ---\n'
    if [ "$STRICT_LIVE" -eq 0 ]; then
        skip "storage runtime checks disabled (STRICT_LIVE=0)"
        return
    fi
    service_file="$DEPLOY_DIR/segdete.service"
    service_user="$(struct_of_file "$service_file" User)"
    save_root="$(env_value_of_file "$service_file" SEGDETE_SAVE_ROOT)"
    log_output="$(struct_of_file "$service_file" StandardOutput)"
    log_file="${log_output#append:}"
    log_root="$(dirname "$log_file")"
    [ -n "$service_user" ] || die "User missing from $service_file"
    [ -n "$save_root" ] || die "SEGDETE_SAVE_ROOT missing from $service_file"
    [ "$log_file" != "$log_output" ] || die "StandardOutput is not append:<path> in $service_file"

    check_access_as_user "$service_user" "$save_root"
    check_access_as_user "$service_user" "$log_root"
    check_disk "$save_root"
    [ "$log_root" = "$save_root" ] || check_disk "$log_root"
}

# ---------------------------------------------------------------- part 7: connected-device inventory
check_expected_count() {
    label="$1"
    actual="$2"
    expected="$3"
    if [ -z "$expected" ]; then
        skip "$label: detected $actual; set HARDWARE_PROFILE or an expected count to assert it"
        return
    fi
    case "$expected" in
        *[!0-9]*) die "invalid expected count for $label: <$expected>" ;;
    esac
    if [ "$actual" -eq "$expected" ]; then
        ok "$label: detected $actual"
    else
        action "DEVICE_COUNT: $label detected=$actual expected=$expected"
    fi
}

normalize_csv() {
    printf '%s\n' "$1" \
        | tr ',' '\n' \
        | sed '/^[[:space:]]*$/d; s/^[[:space:]]*//; s/[[:space:]]*$//' \
        | sort \
        | paste -sd, -
}

check_devices() {
    printf -- '--- 7. device inventory ---\n'
    if [ "$STRICT_LIVE" -eq 0 ]; then
        skip "device inventory disabled (STRICT_LIVE=0)"
        return
    fi
    command -v lsusb >/dev/null 2>&1 || die "lsusb not found"
    usb="$(lsusb 2>/dev/null)"
    basler_count="$(printf '%s\n' "$usb" | grep -Eic 'ID 2676:' || true)"
    buzzer_count="$(printf '%s\n' "$usb" | grep -Eic 'ID 1a86:5523' || true)"
    geoposition_count="$(printf '%s\n' "$usb" | grep -Eic 'ID 1a86:7523' || true)"
    check_expected_count "Basler USB" "$basler_count" "$EXPECTED_BASLER_COUNT"
    check_expected_count "buzzer USB 1a86:5523" "$buzzer_count" "$EXPECTED_BUZZER_COUNT"
    check_expected_count "geoposition USB 1a86:7523" "$geoposition_count" "$EXPECTED_GEOPOSITION_COUNT"

    python="$BACKEND_DIR/.venv/bin/python"
    if [ ! -x "$python" ]; then
        action "PYTHON_MISSING: cannot enumerate pylon devices with $python"
        return
    fi
    service_user="$(struct_of_file "$DEPLOY_DIR/segdete.service" User)"
    if [ -z "$EXPECTED_CAMERA_SNS" ]; then
        case "$HARDWARE_PROFILE" in
            camera|all)
                EXPECTED_CAMERA_SNS="$(env_value_of_file "$DEPLOY_DIR/segdete.service" SEGDETE_CAMERA_SNS)"
                ;;
        esac
    fi
    camera_sns="$(runuser -u "$service_user" -- "$python" -c \
        'from pypylon import pylon; print(",".join(sorted(d.GetSerialNumber() for d in pylon.TlFactory.GetInstance().EnumerateDevices())))' \
        2>/dev/null)"
    rc=$?
    if [ "$rc" -ne 0 ]; then
        action "PYLON_ENUMERATION_FAILED: running as $service_user"
        return
    fi
    if [ -n "$camera_sns" ]; then
        ok "pylon camera serials: $camera_sns"
    else
        ok "pylon camera serials: none"
    fi
    if [ -n "$EXPECTED_CAMERA_SNS" ]; then
        actual_normalized="$(normalize_csv "$camera_sns")"
        expected_normalized="$(normalize_csv "$EXPECTED_CAMERA_SNS")"
        if [ "$actual_normalized" = "$expected_normalized" ]; then
            ok "pylon serials match EXPECTED_CAMERA_SNS"
        else
            action "CAMERA_SERIALS: detected=<$actual_normalized> expected=<$expected_normalized>"
        fi
    fi
}

# ---------------------------------------------------------------- part 8: fatal logs from the current service start
check_fatal_log() {
    unit="$1"
    repo="$DEPLOY_DIR/$unit.service"
    output="$(struct_of_file "$repo" StandardOutput)"
    log_file="${output#append:}"
    [ "$log_file" != "$output" ] || return
    [ -f "$log_file" ] || { action "LOG_MISSING: $unit expected $log_file"; return; }
    active="$(systemctl show "$unit" -p ActiveState --value 2>/dev/null)"
    if [ "$active" != "active" ]; then
        skip "$unit: not active; current-start fatal log scan unavailable"
        return
    fi
    active_ts="$(systemctl show "$unit" -p ActiveEnterTimestamp --value 2>/dev/null)"
    since="$(date -d "$active_ts" '+%Y-%m-%d %H:%M:%S' 2>/dev/null || true)"
    if [ -z "$since" ]; then
        skip "$unit: not active; current-start fatal log scan unavailable"
        return
    fi
    fatal="$(awk -v since="$since" '
        length($0) >= 19 && substr($0, 1, 19) >= since &&
        ($0 ~ /CRITICAL/ || $0 ~ /FATAL/ || $0 ~ /^Traceback/) { print }
    ' "$log_file" | tail -n 20)"
    if [ -z "$fatal" ]; then
        ok "$unit: no fatal log entries since $since"
    else
        action "FATAL_LOGS: $unit since $since"
        printf '%s\n' "$fatal" | sed 's/^/         /'
    fi
}

check_logs() {
    printf -- '--- 8. fatal logs ---\n'
    if [ "$STRICT_LIVE" -eq 0 ]; then
        skip "fatal log checks disabled (STRICT_LIVE=0)"
        return
    fi
    for unit in segdete buzzer geoposition; do
        check_fatal_log "$unit"
    done
}

# ---------------------------------------------------------------- main
printf 'SegDete production verification\n'
printf 'repo: %s\n' "$REPO_ROOT"
case "$STRICT_LIVE" in 0|1) ;; *) die "STRICT_LIVE must be 0 or 1" ;; esac
case "$CHECK_RELEASE" in 0|1) ;; *) die "CHECK_RELEASE must be 0 or 1" ;; esac
case "$MIN_DISK_FREE_KB" in ''|*[!0-9]*) die "MIN_DISK_FREE_KB must be a non-negative integer" ;; esac
case "$MAX_UNIT_RESTARTS" in ''|*[!0-9]*) die "MAX_UNIT_RESTARTS must be a non-negative integer" ;; esac

if [ "$CHECK_RELEASE" -eq 1 ]; then
    check_release
else
    printf -- '--- 0. release identity ---\n'
    skip "release identity disabled (CHECK_RELEASE=0)"
fi
check_venv
printf -- '--- 2. systemd units ---\n'
printf -- '--- 2a. repo vs installed ---\n'
for unit in $UNITS; do
    check_unit_files "$unit"
done
printf -- '--- 2b. live state ---\n'
for unit in $UNITS; do
    check_unit_live "$unit"
done
check_runtime_units
for timer in $TIMERS; do
    check_timer "$timer"
done
check_nginx
check_udev
check_endpoints
check_storage
check_devices
check_logs

printf -- '--- summary: %s ---\n' "$([ "$EXIT" -eq 0 ] && printf 'ALL GREEN' || printf '%s action(s) needed' "$ACTIONS")"
exit "$EXIT"
