import hmac
import io
import uuid
from datetime import date

import pandas as pd
import streamlit as st
from PIL import Image, ImageOps
from supabase import create_client

BUCKET = "invoices"

st.set_page_config(page_title="سيستم محل النضارات", page_icon="👓", layout="centered")
st.markdown(
    """
    <style>
    .stApp, .stMarkdown, label, .stTextInput, .stNumberInput { direction: rtl; text-align: right; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------- الاتصال بقاعدة البيانات ----------
@st.cache_resource
def get_client():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])


sb = get_client()


# ---------- تسجيل الدخول ----------
def require_login():
    if st.session_state.get("ok"):
        return
    st.title("👓 سيستم محل النضارات")
    pw = st.text_input("كلمة السر", type="password")
    if st.button("دخول"):
        if hmac.compare_digest(pw, st.secrets["APP_PASSWORD"]):
            st.session_state["ok"] = True
            st.rerun()
        else:
            st.error("كلمة السر غلط")
    st.stop()


require_login()


# ---------- دوال مساعدة ----------
def compress_image(uploaded):
    """تصغير الصورة عشان تاخد مساحة قليلة."""
    img = Image.open(uploaded)
    img = ImageOps.exif_transpose(img).convert("RGB")
    img.thumbnail((1600, 1600))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=70, optimize=True)
    return buf.getvalue()


def save_image(uploaded):
    if uploaded is None:
        return None
    name = f"{uuid.uuid4().hex}.jpg"
    sb.storage.from_(BUCKET).upload(
        path=name, file=compress_image(uploaded), file_options={"content-type": "image/jpeg"}
    )
    return name


@st.cache_data(show_spinner=False)
def get_image_bytes(name):
    return sb.storage.from_(BUCKET).download(name)


def month_range(year, month):
    start = date(year, month, 1)
    end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return str(start), str(end)


def load_month(table, year, month):
    start, end = month_range(year, month)
    res = (
        sb.table(table)
        .select("*")
        .gte("day", start)
        .lt("day", end)
        .order("day", desc=True)
        .order("id", desc=True)
        .execute()
    )
    return res.data or []


def fetch_all(table):
    rows, offset = [], 0
    while True:
        chunk = sb.table(table).select("*").order("id").range(offset, offset + 999).execute().data
        rows += chunk
        if len(chunk) < 1000:
            return rows
        offset += 1000


# ---------- الصفحة الرئيسية ----------
st.title("👓 سيستم محل النضارات")

today = date.today()
c_y, c_m = st.columns(2)
year = int(c_y.number_input("السنة", 2020, 2100, today.year, step=1))
month = int(c_m.number_input("الشهر", 1, 12, today.month, step=1))

try:
    revs = load_month("revenues", year, month)
    exps = load_month("expenses", year, month)
except Exception as e:
    st.error(f"مشكلة في الاتصال بقاعدة البيانات: {e}")
    st.stop()

total_rev = sum(float(r["amount"]) for r in revs)
total_exp = sum(float(e["amount"]) for e in exps)
profit = total_rev - total_exp

m1, m2 = st.columns(2)
m1.metric("إجمالي الإيرادات", f"{total_rev:,.2f}")
m2.metric("إجمالي المصروفات", f"{total_exp:,.2f}")

if profit > 0:
    st.success(f"✅ ربح الشهر: {profit:,.2f}")
elif profit < 0:
    st.error(f"⚠️ عجز الشهر: {abs(profit):,.2f}")
else:
    st.info("لا ربح ولا خسارة")

st.divider()

# ---------- الإيرادات ----------
with st.expander(f"💰 الإيرادات ({total_rev:,.2f})"):
    with st.form("rev_form", clear_on_submit=True):
        r_day = st.date_input("التاريخ", today, key="r_day")
        r_reason = st.text_input("السبب (مثال: بيع نضارة للعميل أحمد)")
        r_amount = st.number_input("المبلغ", min_value=0.0, step=10.0)
        r_img = st.file_uploader(
            "صورة الفاتورة (ارفع أو صوّر بالكاميرا)",
            type=["jpg", "jpeg", "png", "webp"],
            key="r_img",
        )
        if st.form_submit_button("حفظ الإيراد"):
            if not r_reason.strip() or r_amount <= 0:
                st.warning("اكتب السبب والمبلغ")
            else:
                try:
                    img_name = save_image(r_img)
                    sb.table("revenues").insert(
                        {"day": str(r_day), "reason": r_reason.strip(), "amount": r_amount, "image": img_name}
                    ).execute()
                    st.success("تم الحفظ")
                    st.rerun()
                except Exception as e:
                    st.error(f"حصلت مشكلة في الحفظ: {e}")

    st.markdown("**سجل الإيرادات**")
    if not revs:
        st.caption("مفيش إيرادات في الشهر ده")
    for r in revs:
        with st.expander(f"{r['day']} — {r['reason']} — {float(r['amount']):,.2f}"):
            if r.get("image"):
                try:
                    st.image(get_image_bytes(r["image"]), caption="صورة الفاتورة")
                except Exception:
                    st.caption("تعذر تحميل الصورة")
            else:
                st.caption("مفيش صورة فاتورة")
            if st.button("🗑️ حذف", key=f"del_r_{r['id']}"):
                if r.get("image"):
                    sb.storage.from_(BUCKET).remove([r["image"]])
                sb.table("revenues").delete().eq("id", r["id"]).execute()
                st.rerun()

# ---------- المصروفات ----------
with st.expander(f"💸 المصروفات ({total_exp:,.2f})"):
    with st.form("exp_form", clear_on_submit=True):
        e_day = st.date_input("التاريخ", today, key="e_day")
        e_reason = st.text_input("سبب الصرف (مثال: إيجار، كهرباء، شراء إطارات)")
        e_amount = st.number_input("المبلغ المصروف", min_value=0.0, step=10.0)
        if st.form_submit_button("حفظ المصروف"):
            if not e_reason.strip() or e_amount <= 0:
                st.warning("اكتب السبب والمبلغ")
            else:
                try:
                    sb.table("expenses").insert(
                        {"day": str(e_day), "reason": e_reason.strip(), "amount": e_amount}
                    ).execute()
                    st.success("تم الحفظ")
                    st.rerun()
                except Exception as e:
                    st.error(f"حصلت مشكلة في الحفظ: {e}")

    st.markdown("**سجل المصروفات**")
    if not exps:
        st.caption("مفيش مصروفات في الشهر ده")
    for e in exps:
        c1, c2 = st.columns([4, 1])
        c1.write(f"{e['day']} — {e['reason']} — **{float(e['amount']):,.2f}**")
        if c2.button("🗑️", key=f"del_e_{e['id']}"):
            sb.table("expenses").delete().eq("id", e["id"]).execute()
            st.rerun()

st.divider()

# ---------- نسخة احتياطية ----------
with st.expander("💾 نسخة احتياطية (حمّلها مرة في الأسبوع)"):
    if st.button("جهّز النسخة"):
        st.session_state["bk_rev"] = pd.DataFrame(fetch_all("revenues")).to_csv(index=False).encode("utf-8-sig")
        st.session_state["bk_exp"] = pd.DataFrame(fetch_all("expenses")).to_csv(index=False).encode("utf-8-sig")
    if "bk_rev" in st.session_state:
        st.download_button("⬇️ تحميل الإيرادات", st.session_state["bk_rev"], "revenues.csv", "text/csv")
        st.download_button("⬇️ تحميل المصروفات", st.session_state["bk_exp"], "expenses.csv", "text/csv")

st.caption("المرحلة الجاية: موديلات النضارات والعدسات والخصومات، ثم العملاء والنضارات الجاري تصنيعها، ثم صفحة التسليم
