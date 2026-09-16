"""Compact Target management UI for DEMIS Schema Analyzer."""

from __future__ import annotations

from typing import Any, Callable

import requests
import streamlit as st

from helpers import (
    DISCOVER_SCHEMAS_TIMEOUT_SECONDS,
    HOST_INPUT_HINT,
    TEST_CONNECTION_TIMEOUT_SECONDS,
    credential_status_label,
    format_connection_request_error,
)

DEFAULT_PORTS = {
    "postgresql": 5432,
    "mysql": 3306,
    "mariadb": 3306,
    "oracle": 1521,
}

ApiCall = Callable[..., requests.Response]


def credential_payload_from_state(target_id: int, has_saved_password: bool) -> dict[str, str] | None:
    """Build the per-request credential payload used by Target actions."""
    if has_saved_password:
        return {}
    if st.session_state.get(f"target_temp_passwordless_{target_id}", False):
        return {"password": ""}
    password = st.session_state.get(f"target_temp_password_{target_id}", "")
    if password:
        return {"password": str(password)}
    return None


def default_analysis_schemas(target: dict[str, Any]) -> list[str]:
    schema = str(target.get("default_schema") or "").strip()
    return [schema] if schema else []


def render_target_dashboard(
    *,
    targets: list[dict[str, Any]],
    targets_load_error: str | None,
    api_post: ApiCall,
    api_put: ApiCall,
    api_delete: ApiCall,
    show_response: Callable[[requests.Response], None],
) -> None:
    """Render compact Target cards with actions beside each Target."""

    @st.dialog("Target 추가")
    def add_target_dialog() -> None:
        db_type = st.selectbox(
            "DB Type",
            ["postgresql", "mysql", "mariadb", "oracle"],
            key="dialog_add_target_db_type",
        )
        port = st.number_input(
            "Port",
            min_value=1,
            max_value=65535,
            value=DEFAULT_PORTS.get(db_type, 5432),
            key=f"dialog_add_target_port_{db_type}",
        )
        with st.form("dialog_add_target_form", clear_on_submit=True):
            source_name = st.text_input("Source Name", placeholder="my_target")
            host = st.text_input("Host", value="localhost")
            st.caption(HOST_INPUT_HINT)
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            st.caption(
                "비밀번호가 없는 계정은 공란으로 등록할 수 있습니다. "
                "입력값은 Catalog DB에 암호화되어 저장되며 평문으로 표시되지 않습니다."
            )

            database_name = ""
            default_schema = "public"
            service_name = ""
            connection_options: dict[str, Any] | None = None

            if db_type == "postgresql":
                database_name = st.text_input("Database", value="")
                default_schema = st.text_input("Schema", value="public")
            elif db_type in {"mysql", "mariadb"}:
                database_name = st.text_input("Database", value="")
                st.caption("MySQL/MariaDB는 Database 이름을 기본 Schema로 사용합니다.")
            else:
                service_name = st.text_input("Service Name", value="")
                default_schema = st.text_input("Schema / Owner", value="")

            enabled = st.checkbox("Enabled", value=True)
            submitted = st.form_submit_button("Target 추가", type="primary")

        if not submitted:
            return
        if db_type in {"mysql", "mariadb"}:
            default_schema = database_name
        if db_type == "oracle":
            database_name = service_name
            connection_options = {"service_name": service_name} if service_name else None

        missing = []
        if not source_name.strip():
            missing.append("source_name")
        if not host.strip():
            missing.append("host")
        if not str(database_name).strip():
            missing.append("database/service_name")
        if not str(default_schema).strip():
            missing.append("default_schema")
        if not username.strip():
            missing.append("username")
        if missing:
            st.error(f"필수 항목 누락: {', '.join(missing)}")
            return

        payload = {
            "source_name": source_name.strip(),
            "db_type": db_type,
            "host": host.strip(),
            "port": int(port),
            "database_name": str(database_name).strip(),
            "default_schema": str(default_schema).strip(),
            "username": username.strip(),
            "password": password,
            "connection_options": connection_options,
            "enabled": enabled,
        }
        try:
            response = api_post("/api/v1/targets", json=payload, timeout=30)
            show_response(response)
            if response.ok:
                st.rerun()
        except Exception as exc:  # noqa: BLE001
            st.error(f"Target 생성 실패: {exc}")

    @st.dialog("Target 수정")
    def edit_target_dialog(target: dict[str, Any]) -> None:
        target_id = int(target["id"])
        has_saved = bool(target.get("has_saved_password"))
        db_types = ["postgresql", "mysql", "mariadb", "oracle"]
        current_db_type = target.get("db_type") or "postgresql"
        edit_db_type = st.selectbox(
            "DB Type",
            db_types,
            index=db_types.index(current_db_type),
            key=f"dialog_edit_db_type_{target_id}",
        )
        with st.form(f"dialog_edit_target_form_{target_id}"):
            edit_name = st.text_input("Source Name", value=target.get("source_name") or "")
            edit_host = st.text_input("Host", value=target.get("host") or "")
            st.caption(HOST_INPUT_HINT)
            edit_port = st.number_input(
                "Port",
                min_value=1,
                max_value=65535,
                value=int(target.get("port") or DEFAULT_PORTS.get(edit_db_type, 5432)),
            )
            edit_username = st.text_input("Username", value=target.get("username") or "")
            edit_database = st.text_input(
                "Database / Service Name",
                value=target.get("database_name") or "",
            )
            edit_schema = st.text_input(
                "Default Schema / Owner",
                value=target.get("default_schema") or "",
            )
            st.caption(
                f"Saved credential: {'있음' if has_saved else '없음'} — "
                "Password를 비워두면 기존 Credential을 유지합니다."
            )
            clear_saved = st.checkbox("저장된 Credential 삭제", value=False)
            set_empty_password = st.checkbox("빈 비밀번호로 변경", value=False)
            edit_password = st.text_input(
                "Password",
                type="password",
                disabled=clear_saved or set_empty_password,
            )
            edit_enabled = st.checkbox("Enabled", value=bool(target.get("enabled", True)))
            save_edit = st.form_submit_button("저장", type="primary")

        if not save_edit:
            return
        credential_change_count = sum(
            [bool(edit_password), bool(clear_saved), bool(set_empty_password)]
        )
        if credential_change_count > 1:
            st.error("Password 변경, 빈 비밀번호 변경, Credential 삭제 중 하나만 선택하세요.")
            return

        update_payload: dict[str, Any] = {
            "source_name": edit_name.strip(),
            "db_type": edit_db_type,
            "host": edit_host.strip(),
            "port": int(edit_port),
            "database_name": edit_database.strip(),
            "default_schema": edit_schema.strip() or "public",
            "username": edit_username.strip(),
            "enabled": edit_enabled,
            "clear_saved_password": clear_saved,
        }
        if edit_db_type == "oracle":
            update_payload["connection_options"] = (
                {"service_name": edit_database.strip()} if edit_database.strip() else None
            )
        if set_empty_password:
            update_payload["password"] = ""
        elif edit_password:
            update_payload["password"] = edit_password

        try:
            response = api_put(
                f"/api/v1/targets/{target_id}",
                json=update_payload,
                timeout=30,
            )
            show_response(response)
            if response.ok:
                st.rerun()
        except Exception as exc:  # noqa: BLE001
            st.error(f"Target 수정 실패: {exc}")

    @st.dialog("Target 삭제")
    def delete_target_dialog(target: dict[str, Any]) -> None:
        target_id = int(target["id"])
        source_name = target.get("source_name") or ""
        st.warning("삭제하면 이 Target의 Catalog / Search Document / Embedding 데이터가 함께 제거됩니다.")
        confirm_name = st.text_input(
            "삭제 확인을 위해 Source Name을 입력하세요",
            key=f"dialog_delete_confirm_{target_id}",
        )
        if st.button("삭제 확인", type="primary", key=f"dialog_delete_btn_{target_id}"):
            if confirm_name.strip() != source_name:
                st.error("Source Name이 일치하지 않습니다.")
                return
            try:
                response = api_delete(f"/api/v1/targets/{target_id}", timeout=60)
                if response.status_code == 204:
                    st.rerun()
                else:
                    show_response(response)
            except Exception as exc:  # noqa: BLE001
                st.error(f"Target 삭제 실패: {exc}")

    @st.dialog("Target 고급 작업")
    def advanced_target_dialog(target: dict[str, Any]) -> None:
        target_id = int(target["id"])
        source_name = target.get("source_name") or ""
        has_saved = bool(target.get("has_saved_password"))

        st.markdown(f"**{source_name}**")
        if not has_saved:
            st.warning("저장된 Credential이 없습니다. 아래 임시 Credential은 요청에만 사용되고 저장되지 않습니다.")
            passwordless = st.checkbox(
                "임시 빈 비밀번호 사용",
                value=bool(st.session_state.get(f"target_temp_passwordless_{target_id}", False)),
                key=f"target_temp_passwordless_{target_id}",
            )
            st.text_input(
                "임시 Password",
                type="password",
                key=f"target_temp_password_{target_id}",
                disabled=passwordless,
            )

        if st.button("Schema 목록 조회", key=f"dialog_discover_{target_id}"):
            body = credential_payload_from_state(target_id, has_saved)
            if body is None:
                st.error("Credential이 없습니다. 임시 Credential을 입력하세요.")
            else:
                try:
                    response = api_post(
                        f"/api/v1/targets/{target_id}/schemas",
                        json=body,
                        timeout=DISCOVER_SCHEMAS_TIMEOUT_SECONDS,
                    )
                    show_response(response)
                    if response.ok:
                        st.session_state[f"discovered_schemas_{target_id}"] = (
                            response.json().get("schemas") or []
                        )
                except Exception as exc:  # noqa: BLE001
                    st.error(format_connection_request_error(exc))

        discovered = st.session_state.get(f"discovered_schemas_{target_id}", [])
        options = discovered or default_analysis_schemas(target)
        current = st.session_state.get(f"analysis_schemas_{target_id}")
        defaults = [s for s in (current or default_analysis_schemas(target)) if s in options]
        st.multiselect(
            "분석 Schema",
            options=options,
            default=defaults,
            key=f"analysis_schemas_{target_id}",
        )

        st.divider()
        st.markdown("**Embedding Pipeline**")
        p1, p2 = st.columns(2)
        if p1.button("Search Docs 재생성", key=f"dialog_rebuild_{target_id}"):
            try:
                response = api_post(
                    f"/api/v1/embeddings/documents/rebuild?source={source_name}",
                    timeout=300,
                )
                show_response(response)
            except Exception as exc:  # noqa: BLE001
                st.error(f"Rebuild Docs 실패: {exc}")
        if p2.button("Embedding 실행", key=f"dialog_embed_{target_id}"):
            try:
                response = api_post(
                    f"/api/v1/embeddings/run?source={source_name}",
                    timeout=3600,
                )
                show_response(response)
            except Exception as exc:  # noqa: BLE001
                st.error(f"Embedding Run 실패: {exc}")

    header, add_col = st.columns([5, 1])
    header.markdown("### DB Targets")
    if add_col.button("➕ Target 추가", type="primary", use_container_width=True):
        add_target_dialog()

    if targets_load_error:
        st.warning(f"Target 목록을 불러오지 못했습니다: {targets_load_error}")
    if not targets:
        st.info("등록된 Target이 없습니다. Target을 추가하세요.")
        return

    for target in targets:
        target_id = int(target["id"])
        source_name = target.get("source_name") or f"target-{target_id}"
        has_saved = bool(target.get("has_saved_password"))
        db_type = str(target.get("db_type") or "-").upper()
        host = target.get("host") or "-"
        port = target.get("port") or "-"
        database = target.get("database_name") or "-"
        schema = target.get("default_schema") or "-"
        enabled = bool(target.get("enabled", True))

        with st.container(border=True):
            title_col, state_col = st.columns([5, 1])
            title_col.markdown(f"#### {source_name}")
            state_col.markdown("🟢 Enabled" if enabled else "⚪ Disabled")
            st.caption(
                f"{db_type} · `{host}:{port}` · DB/Service `{database}` · "
                f"Schema `{schema}` · User `{target.get('username') or '-'}` · "
                f"Credential {credential_status_label(has_saved)}"
            )
            if not has_saved:
                st.caption("저장된 Credential이 없으면 **고급 작업**에서 임시 Credential을 먼저 입력하세요.")

            a1, a2, a3, a4, a5 = st.columns(5)
            if a1.button(
                "연결 테스트",
                key=f"target_test_{target_id}",
                use_container_width=True,
            ):
                body = credential_payload_from_state(target_id, has_saved)
                if body is None:
                    st.error("Credential이 없습니다. 고급 작업에서 임시 Credential을 입력하세요.")
                else:
                    try:
                        response = api_post(
                            f"/api/v1/targets/{target_id}/test",
                            json=body,
                            timeout=TEST_CONNECTION_TIMEOUT_SECONDS,
                        )
                        show_response(response)
                    except Exception as exc:  # noqa: BLE001
                        st.error(format_connection_request_error(exc))

            if a2.button(
                "Schema 분석",
                key=f"target_analyze_{target_id}",
                type="primary",
                use_container_width=True,
            ):
                body = credential_payload_from_state(target_id, has_saved)
                schemas = st.session_state.get(
                    f"analysis_schemas_{target_id}", default_analysis_schemas(target)
                )
                if body is None:
                    st.error("Credential이 없습니다. 고급 작업에서 임시 Credential을 입력하세요.")
                elif not schemas:
                    st.error("분석할 Schema가 없습니다. 고급 작업에서 Schema를 선택하세요.")
                else:
                    payload: dict[str, Any] = {"schemas": schemas}
                    if "password" in body:
                        payload["password"] = body["password"]
                    try:
                        response = api_post(
                            f"/api/v1/targets/{target_id}/analyze",
                            json=payload,
                            timeout=600,
                        )
                        show_response(response)
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"Analyze 실패: {exc}")

            if a3.button("수정", key=f"target_edit_{target_id}", use_container_width=True):
                edit_target_dialog(target)
            if a4.button("고급 작업", key=f"target_advanced_{target_id}", use_container_width=True):
                advanced_target_dialog(target)
            if a5.button("삭제", key=f"target_delete_{target_id}", use_container_width=True):
                delete_target_dialog(target)
