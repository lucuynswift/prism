# 文件位置：本地 prism-main/auth.py
# 推送到：GitHub prism-main 仓库
# 运行在：Streamlit Cloud

import streamlit as st
import requests
import time

# ══════════════════════════════════════════
# ★ 无需在这里填写，自动从 secrets.toml 读取
# ══════════════════════════════════════════
AUTH_BASE = st.secrets["AUTH_BASE_URL"]


def api_post(endpoint: str, body: dict, token: str = None) -> tuple[bool, dict]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        resp = requests.post(
            f"{AUTH_BASE}/{endpoint}",
            json=body,
            headers=headers,
            timeout=5
        )
        return resp.ok, resp.json()
    except requests.exceptions.ConnectionError:
        return False, {"detail": "Cannot connect to auth server. Please try again."}
    except Exception as e:
        return False, {"detail": str(e)}


def render_auth_sidebar():
    # 处理重置密码跳转
    reset_token = st.query_params.get("reset_token")
    if reset_token:
        _render_reset_form(reset_token)
        return

    if st.session_state.get("current_user"):
        st.sidebar.success(
            f"✅ Logged in as **{st.session_state['current_user']}**")
        if st.sidebar.button("Log out"):
            st.session_state["current_user"] = None
            st.session_state["auth_token"]   = None
            st.session_state.pop("_subscription_cache", None)
            st.rerun()
        return

    tab_login, tab_register, tab_forgot = st.sidebar.tabs(
        ["Log in", "Register", "Forgot password"])

    with tab_login:
        email    = st.text_input("Email",    key="li_email")
        password = st.text_input("Password", key="li_pw", type="password")
        if st.button("Log in", key="btn_li"):
            if not email or not password:
                st.error("Please fill in all fields.")
            else:
                ok, data = api_post("login",
                                    {"email": email, "password": password})
                if ok:
                    st.session_state["current_user"] = data["username"]
                    st.session_state["auth_token"]   = data["token"]
                    st.rerun()
                else:
                    st.error(data.get("detail", "Login failed."))

    with tab_register:
        uname    = st.text_input("Username",         key="reg_u")
        email    = st.text_input("Email",            key="reg_e")
        password = st.text_input("Password",         key="reg_p",  type="password")
        confirm  = st.text_input("Confirm password", key="reg_c",  type="password")
        if st.button("Register", key="btn_reg"):
            if not all([uname, email, password, confirm]):
                st.error("Please fill in all fields.")
            elif password != confirm:
                st.error("Passwords do not match.")
            elif len(password) < 8:
                st.error("Password must be at least 8 characters.")
            else:
                ok, data = api_post("register",
                                    {"username": uname,
                                     "email":    email,
                                     "password": password})
                if ok:
                    st.success("Registered! Please log in.")
                else:
                    st.error(data.get("detail", "Registration failed."))

    with tab_forgot:
        email = st.text_input("Your email", key="fg_e")
        if st.button("Send reset link", key="btn_fg"):
            if not email:
                st.error("Please enter your email.")
            else:
                api_post("reset-request", {"email": email})
                st.info("If this email is registered, a reset link has been sent.")


def _render_reset_form(token: str):
    st.title("🔑 Reset Password")
    pw  = st.text_input("New password",     type="password")
    pw2 = st.text_input("Confirm password", type="password")
    if st.button("Reset password"):
        if pw != pw2:
            st.error("Passwords do not match.")
        elif len(pw) < 8:
            st.error("Minimum 8 characters.")
        else:
            ok, data = api_post("reset-password",
                                {"token": token, "new_password": pw})
            if ok:
                st.success("Password reset! Please log in.")
                st.query_params.clear()
                st.rerun()
            else:
                st.error(data.get("detail", "Link expired or invalid."))


def check_subscription() -> dict:
    token = st.session_state.get("auth_token")
    if not token:
        return {"subscribed": False, "plan": None}
    cache     = "_subscription_cache"
    cache_t   = "_subscription_cache_time"
    if (cache in st.session_state and
            time.time() - st.session_state.get(cache_t, 0) < 300):
        return st.session_state[cache]
    try:
        resp = requests.post(
            f"{AUTH_BASE}/subscription-status",
            headers={"Authorization": f"Bearer {token}"},
            timeout=5)
        if resp.ok:
            result = resp.json()
            st.session_state[cache]   = result
            st.session_state[cache_t] = time.time()
            return result
    except Exception:
        pass
    return {"subscribed": False, "plan": None}


def render_subscription_sidebar():
    token = st.session_state.get("auth_token")
    if not token:
        return
    sub = check_subscription()
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 💎 Subscription")
    if sub["subscribed"]:
        import datetime
        exp = (datetime.datetime.fromtimestamp(sub["expires_at"]).strftime("%Y-%m-%d")
               if sub.get("expires_at") else "—")
        st.sidebar.success(f"✅ **{sub['plan'].capitalize()} plan**\nExpires: {exp}")
    else:
        st.sidebar.warning("📖 Free plan — 10 sentences/day")
        col1, col2 = st.sidebar.columns(2)
        with col1:
            if st.button("$9.9/mo", use_container_width=True):
                _checkout("monthly")
        with col2:
            if st.button("$79/yr", use_container_width=True):
                _checkout("yearly")


def _checkout(plan: str):
    token = st.session_state.get("auth_token")
    ok, data = api_post("create-checkout", {"plan": plan}, token=token)
    if ok:
        url = data["checkout_url"]
        st.markdown(
            f'<meta http-equiv="refresh" content="0;url={url}">',
            unsafe_allow_html=True)
    else:
        st.error("Failed to create checkout, please try again.")