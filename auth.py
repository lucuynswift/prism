# streamlit run "D:\prism-main\app.py"
# ============================================================
# 文件② prism-main/auth.py（Gumroad 版本）
#
# 相对上一版（Lemon Squeezy）的改动：
#   [改动1] 文件顶部：删除 Lemon Squeezy 相关常量，新增 Gumroad 常量
#   [改动2] render_subscription_sidebar()：
#           删除"跳转付款链接"按钮，改为"输入激活码"表单
#   [改动3] check_subscription()：完全不变，仍从服务器查询订阅状态
#   [改动4] _checkout()：整个函数删除，改为 _render_license_input()
#   [不变]  render_auth_sidebar() 全部不变
#   [不变]  _render_reset_form() 全部不变
#   [不变]  api_post() 全部不变
#
# Gumroad 激活流程：
#   用户在 Gumroad 购买 → 收到含 License Key 的邮件
#   → 在侧边栏输入 License Key → auth.py 调用服务器 /activate-license
#   → 服务器调用 Gumroad API 验证 Key → 验证通过则写入 subscriptions 表
# ============================================================

import streamlit as st
import requests
import time

# ============================================================
# [改动1] Gumroad 常量
# 从 secrets.toml 读取，不在这里填写
# ============================================================
AUTH_BASE = st.secrets["AUTH_BASE_URL"]
# 注意：GUMROAD_* 密钥在服务器 .env 里，不在前端 secrets.toml


# ============================================================
# 工具函数（不变）
# ============================================================
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


# ============================================================
# 认证侧边栏（完全不变）
# ============================================================
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
            st.session_state.pop("_subscription_cache",      None)
            st.session_state.pop("_subscription_cache_time", None)
            st.session_state.pop("sub", None)  # 如果你换成了 sub
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
        password = st.text_input("Password",         key="reg_p", type="password")
        confirm  = st.text_input("Confirm password", key="reg_c", type="password")
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


# ============================================================
# 重置密码表单（完全不变）
# ============================================================
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


# ============================================================
# 查询订阅状态（完全不变，仍从服务器查）
# ============================================================
def check_subscription() -> dict:
    # 🏎️ 专为 Paddle 审核员开辟的绿色通道
    # 假设你在 st.session_state.current_user 里存了当前登录的用户名
    current_user = st.session_state.get("current_user")
    if current_user == "lucy.n.swift@gmail.com":
        return True  # 直接判定为已订阅，跳过后续所有数据库检查
    #===========================================================
    token = st.session_state.get("auth_token")
    if not token:
        return {"subscribed": False, "plan": None, "expires_at": None}

    cache   = "_subscription_cache"
    cache_t = "_subscription_cache_time"
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
    return {"subscribed": False, "plan": None, "expires_at": None}


# ============================================================
# [改动2] 订阅侧边栏
# 删除"跳转付款链接"按钮，改为：
#   - 显示 Gumroad 购买链接（外链，新标签页打开）
#   - 提供 License Key 输入框
# ============================================================
def render_subscription_sidebar():
    token = st.session_state.get("auth_token")
    if not token:
        return

    sub = check_subscription()
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 💎 Subscription")

    if sub["subscribed"]:
        import datetime
        exp = (datetime.datetime.fromtimestamp(
                   sub["expires_at"]).strftime("%Y-%m-%d")
               if sub.get("expires_at") else "—")
        plan_label = sub.get("plan", "").capitalize()
        st.sidebar.success(f"✅ **{plan_label} plan**\n\nExpires: {exp}")

        # 已订阅用户：显示联系支持入口
        with st.sidebar.expander("Manage subscription"):
            st.write(
                "To cancel or get a refund, "
                "please contact us with your Gumroad order email:")
            st.code("support@syntax-master.com")  # ★ 填你的支持邮箱

    else:
        # ── 未订阅：显示购买链接 + License Key 输入框 ──
        st.sidebar.warning("📖 Free trial / Free plan")

        st.sidebar.markdown("**Unlock unlimited reading:**")

        # Gumroad 购买链接（在新标签页打开，不刷新当前页）
        # ★ 把下面两个 URL 替换成你在 Gumroad 创建的产品链接
        MONTHLY_URL = "https://★你的用户名★.gumroad.com/l/★月订阅产品Permalink★"
        YEARLY_URL  = "https://★你的用户名★.gumroad.com/l/★年订阅产品Permalink★"

        col1, col2 = st.sidebar.columns(2)
        with col1:
            st.markdown(
                f'<a href="{MONTHLY_URL}" target="_blank">'
                f'<button style="width:100%;padding:8px;background:#1a1209;'
                f'color:#f7f0e3;border:none;border-radius:4px;cursor:pointer;'
                f'font-size:13px;">$9.9 / mo</button></a>',
                unsafe_allow_html=True)
        with col2:
            st.markdown(
                f'<a href="{YEARLY_URL}" target="_blank">'
                f'<button style="width:100%;padding:8px;background:#1a1209;'
                f'color:#f7f0e3;border:none;border-radius:4px;cursor:pointer;'
                f'font-size:13px;">$79 / yr</button></a>',
                unsafe_allow_html=True)

        st.sidebar.caption(
            "After purchase, check your email for the License Key.")

        # License Key 激活表单
        st.sidebar.markdown("**Already purchased? Enter your License Key:**")
        _render_license_input()


# ============================================================
# [改动4] License Key 激活表单
# 替换原来的 _checkout() 函数
# 调用服务器 /activate-license 接口，由服务器验证 Gumroad License Key
# ============================================================
def _render_license_input():
    license_key = st.sidebar.text_input(
        "License Key",
        placeholder="XXXXXXXX-XXXXXXXX-XXXXXXXX-XXXXXXXX",
        key="license_key_input"
    )

    if st.sidebar.button("Activate", key="btn_activate"):
        if not license_key or len(license_key.strip()) < 10:
            st.sidebar.error("Please enter a valid License Key.")
            return

        token = st.session_state.get("auth_token")
        if not token:
            st.sidebar.error("Please log in first.")
            return

        with st.sidebar.spinner("Verifying…"):
            ok, data = api_post(
                "activate-license",
                {"license_key": license_key.strip().upper()},
                token=token
            )

        if ok:
            plan      = data.get("plan", "")
            expires   = data.get("expires_at", "")
            import datetime
            exp_str = (datetime.datetime.fromtimestamp(expires).strftime("%Y-%m-%d")
                       if expires else "—")
            st.sidebar.success(
                f"✅ Activated! **{plan.capitalize()} plan** until {exp_str}")
            # 清除订阅缓存，让下次查询拿到最新状态
            st.session_state.pop("_subscription_cache",      None)
            st.session_state.pop("_subscription_cache_time", None)
            # 🔥 你只需要在这里，全自动地把你在 app.py 里新定义的 "sub" 缓存也擦除掉：
            st.session_state.pop("sub", None)
            st.rerun()
        else:
            err = data.get("detail", "Activation failed.")
            if "used" in err.lower():
                st.sidebar.error(
                    "This key has already been used. "
                    "Contact support if this is a mistake.")
            elif "not found" in err.lower():
                st.sidebar.error(
                    "Key not found. Please check and try again.")
            else:
                st.sidebar.error(err)
# # ============================================================
# # 文件② prism-main/auth.py
# # 改动位置：文件末尾 _checkout() 函数
# # 改动原因：替换 Lemon Squeezy 为新支付平台
# # 其余代码（认证部分）完全不变
# # ============================================================
#
# # 文件位置：本地 prism-main/auth.py
# # 推送到：GitHub prism-main 仓库
# # 运行在：Streamlit Cloud
#
# import streamlit as st
# import requests
# import time
#
# # ══════════════════════════════════════════
# # ★ 无需在这里填写，自动从 secrets.toml 读取
# # ══════════════════════════════════════════
# AUTH_BASE = st.secrets["AUTH_BASE_URL"]
#
#
# def api_post(endpoint: str, body: dict, token: str = None) -> tuple[bool, dict]:
#     headers = {"Content-Type": "application/json"}
#     if token:
#         headers["Authorization"] = f"Bearer {token}"
#     try:
#         resp = requests.post(
#             f"{AUTH_BASE}/{endpoint}",
#             json=body,
#             headers=headers,
#             timeout=5
#         )
#         return resp.ok, resp.json()
#     except requests.exceptions.ConnectionError:
#         return False, {"detail": "Cannot connect to auth server. Please try again."}
#     except Exception as e:
#         return False, {"detail": str(e)}
#
#
# def render_auth_sidebar():
#     # 处理重置密码跳转
#     reset_token = st.query_params.get("reset_token")
#     if reset_token:
#         _render_reset_form(reset_token)
#         return
#
#     if st.session_state.get("current_user"):
#         st.sidebar.success(
#             f"✅ Logged in as **{st.session_state['current_user']}**")
#         if st.sidebar.button("Log out"):
#             st.session_state["current_user"] = None
#             st.session_state["auth_token"]   = None
#             st.session_state.pop("_subscription_cache", None)
#             st.rerun()
#         return
#
#     tab_login, tab_register, tab_forgot = st.sidebar.tabs(
#         ["Log in", "Register", "Forgot password"])
#
#     with tab_login:
#         email    = st.text_input("Email",    key="li_email")
#         password = st.text_input("Password", key="li_pw", type="password")
#         if st.button("Log in", key="btn_li"):
#             if not email or not password:
#                 st.error("Please fill in all fields.")
#             else:
#                 ok, data = api_post("login",
#                                     {"email": email, "password": password})
#                 if ok:
#                     st.session_state["current_user"] = data["username"]
#                     st.session_state["auth_token"]   = data["token"]
#                     st.rerun()
#                 else:
#                     st.error(data.get("detail", "Login failed."))
#
#     with tab_register:
#         uname    = st.text_input("Username",         key="reg_u")
#         email    = st.text_input("Email",            key="reg_e")
#         password = st.text_input("Password",         key="reg_p",  type="password")
#         confirm  = st.text_input("Confirm password", key="reg_c",  type="password")
#         if st.button("Register", key="btn_reg"):
#             if not all([uname, email, password, confirm]):
#                 st.error("Please fill in all fields.")
#             elif password != confirm:
#                 st.error("Passwords do not match.")
#             elif len(password) < 8:
#                 st.error("Password must be at least 8 characters.")
#             else:
#                 ok, data = api_post("register",
#                                     {"username": uname,
#                                      "email":    email,
#                                      "password": password})
#                 if ok:
#                     st.success("Registered! Please log in.")
#                 else:
#                     st.error(data.get("detail", "Registration failed."))
#
#     with tab_forgot:
#         email = st.text_input("Your email", key="fg_e")
#         if st.button("Send reset link", key="btn_fg"):
#             if not email:
#                 st.error("Please enter your email.")
#             else:
#                 api_post("reset-request", {"email": email})
#                 st.info("If this email is registered, a reset link has been sent.")
#
#
# def _render_reset_form(token: str):
#     st.title("🔑 Reset Password")
#     pw  = st.text_input("New password",     type="password")
#     pw2 = st.text_input("Confirm password", type="password")
#     if st.button("Reset password"):
#         if pw != pw2:
#             st.error("Passwords do not match.")
#         elif len(pw) < 8:
#             st.error("Minimum 8 characters.")
#         else:
#             ok, data = api_post("reset-password",
#                                 {"token": token, "new_password": pw})
#             if ok:
#                 st.success("Password reset! Please log in.")
#                 st.query_params.clear()
#                 st.rerun()
#             else:
#                 st.error(data.get("detail", "Link expired or invalid."))
#
#
# def check_subscription() -> dict:
#     token = st.session_state.get("auth_token")
#     if not token:
#         return {"subscribed": False, "plan": None}
#     cache     = "_subscription_cache"
#     cache_t   = "_subscription_cache_time"
#     if (cache in st.session_state and
#             time.time() - st.session_state.get(cache_t, 0) < 300):
#         return st.session_state[cache]
#     try:
#         resp = requests.post(
#             f"{AUTH_BASE}/subscription-status",
#             headers={"Authorization": f"Bearer {token}"},
#             timeout=5)
#         if resp.ok:
#             result = resp.json()
#             st.session_state[cache]   = result
#             st.session_state[cache_t] = time.time()
#             return result
#     except Exception:
#         pass
#     return {"subscribed": False, "plan": None}
#
#
# def render_subscription_sidebar():
#     token = st.session_state.get("auth_token")
#     if not token:
#         return
#     sub = check_subscription()
#     st.sidebar.markdown("---")
#     st.sidebar.markdown("### 💎 Subscription")
#     if sub["subscribed"]:
#         import datetime
#         exp = (datetime.datetime.fromtimestamp(sub["expires_at"]).strftime("%Y-%m-%d")
#                if sub.get("expires_at") else "—")
#         st.sidebar.success(f"✅ **{sub['plan'].capitalize()} plan**\nExpires: {exp}")
#     else:
#         st.sidebar.warning("📖 Free plan — 10 sentences/day")
#         col1, col2 = st.sidebar.columns(2)
#         with col1:
#             if st.button("$9.9/mo", use_container_width=True):
#                 _checkout("monthly")
#         with col2:
#             if st.button("$79/yr", use_container_width=True):
#                 _checkout("yearly")
#
#
# # def _checkout(plan: str):
# #     token = st.session_state.get("auth_token")
# #     ok, data = api_post("create-checkout", {"plan": plan}, token=token)
# #     if ok:
# #         url = data["checkout_url"]
# #         st.markdown(
# #             f'<meta http-equiv="refresh" content="0;url={url}">',
# #             unsafe_allow_html=True)
# #     else:
# #         st.error("Failed to create checkout, please try again.")
# def _checkout(plan: str):
#     """
#     跳转到 Paddle 托管的结账页面。
#     Paddle Variant ID 在 Paddle 控制台 → Catalog → Products 里找。
#     """
#     token = st.session_state.get("auth_token")
#     ok, data = api_post("create-checkout", {"plan": plan}, token=token)
#     if ok:
#         url = data["checkout_url"]
#         # 在当前页打开 Paddle overlay
#         st.markdown(
#             f'<meta http-equiv="refresh" content="0;url={url}">',
#             unsafe_allow_html=True)
#     else:
#         st.error("Failed to create checkout. Please try again.")
#
#
# # # ============================================================
# # # 文件② prism-main/auth.py
# # # 改动位置：文件末尾 _checkout() 函数
# # # 改动原因：替换 Lemon Squeezy 为新支付平台
# # # 其余代码（认证部分）完全不变
# # # ============================================================
# #
# # # ── 以下三个方案三选一 ──────────────────────────────────────
# #
# # # ======== 方案A：Paddle ========
# # def _checkout(plan: str):
# #     """
# #     跳转到 Paddle 托管的结账页面。
# #     Paddle Variant ID 在 Paddle 控制台 → Catalog → Products 里找。
# #     """
# #     token = st.session_state.get("auth_token")
# #     ok, data = api_post("create-checkout", {"plan": plan}, token=token)
# #     if ok:
# #         url = data["checkout_url"]
# #         # 在当前页打开 Paddle overlay
# #         st.markdown(
# #             f'<meta http-equiv="refresh" content="0;url={url}">',
# #             unsafe_allow_html=True)
# #     else:
# #         st.error("Failed to create checkout. Please try again.")
# #
# # # ======== 方案B：Ko-fi ========
# # # def _checkout(plan: str):
# # #     """
# # #     Ko-fi 不支持动态生成链接，直接跳转到你的 Ko-fi 主页。
# # #     用户在 Ko-fi 完成付款后，你手动在后台激活订阅。
# # #     适合早期用户量少的阶段。
# # #     """
# # #     KOFI_URL = st.secrets.get("KOFI_URL", "https://ko-fi.com/你的用户名")
# # #     st.markdown(
# # #         f'<meta http-equiv="refresh" content="0;url={KOFI_URL}">',
# # #         unsafe_allow_html=True)
# # #     st.info("You will be redirected to Ko-fi to complete payment.")
# #
# # # ======== 方案C：Stripe（需要香港公司） ========
# # # def _checkout(plan: str):
# # #     token = st.session_state.get("auth_token")
# # #     ok, data = api_post("create-checkout", {"plan": plan}, token=token)
# # #     if ok:
# # #         url = data["checkout_url"]
# # #         st.markdown(
# # #             f'<meta http-equiv="refresh" content="0;url={url}">',
# # #             unsafe_allow_html=True)
# # #     else:
# # #         st.error("Failed to create checkout. Please try again.")
