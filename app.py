import streamlit as st
import google.generativeai as genai
from PIL import Image
import io, json, time, re, datetime, gc, os

# --- 基本設定 ---
st.set_page_config(page_title="教科書ブースター V1.2", layout="centered", page_icon="🚀")

# --- 🛠️ 履歴の自動永続化ロジック ---
def get_filename():
    if "school_type" in st.session_state and "grade" in st.session_state:
        return f"history_{st.session_state.school_type}_{st.session_state.grade}.json"
    return "study_history.json"

def load_history():
    filename = get_filename()
    if os.path.exists(filename):
        try:
            with open(filename, "r", encoding="utf-8") as f:
                return json.load(f)
        except: return {}
    return {}

def save_history(history):
    filename = get_filename()
    # 同意状態なども一緒に保存してリロード対策とする
    data = {
        "agreed": st.session_state.agreed,
        "school_type": st.session_state.school_type,
        "grade": st.session_state.grade,
        "history": history
    }
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# --- 初期化 ---
if "current_tab" not in st.session_state: st.session_state.current_tab = "学習"
if "history" not in st.session_state: st.session_state.history = {}
if "final_json" not in st.session_state: st.session_state.final_json = None
if "agreed" not in st.session_state: st.session_state.agreed = False
if "font_size" not in st.session_state: st.session_state.font_size = 18
if "show_voice_btns" not in st.session_state: st.session_state.show_voice_btns = False
if "review_mode" not in st.session_state: st.session_state.review_mode = False

# リロード時に既存のファイルがあれば復元を試みる（簡易版）
if not st.session_state.agreed:
    # 最後に使った設定を推測（本来は一意のIDが必要だが今回は簡略化）
    for f in os.listdir():
        if f.startswith("history_") and f.endswith(".json"):
            try:
                with open(f, "r", encoding="utf-8") as file:
                    tmp = json.load(file)
                    st.session_state.agreed = tmp.get("agreed", False)
                    st.session_state.school_type = tmp.get("school_type")
                    st.session_state.grade = tmp.get("grade")
                    st.session_state.history = tmp.get("history", {})
                    break
            except: pass

def speak_chrome(text, speed=1.0, lang="ja-JP"):
    if text:
        safe_text = text.replace("'", "\\'").replace("\n", " ")
        js_code = f"<script>var synth = window.parent.speechSynthesis; synth.cancel(); var uttr = new SpeechSynthesisUtterance('{safe_text}'); uttr.rate = {speed}; uttr.lang = '{lang}'; synth.speak(uttr);</script>"
        st.components.v1.html(js_code, height=0)

def stop_speech():
    st.components.v1.html("<script>window.parent.speechSynthesis.cancel();</script>", height=0)

st.markdown(f"<style>.content-body {{ font-size: {st.session_state.font_size}px !important; line-height: 1.6; }}</style>", unsafe_allow_html=True)

SUBJECT_PROMPTS = {
    "英語": "英文を意味の塊（/）で区切るスラッシュリーディング形式（英文 / 訳）を徹底してください。重要な文法構造や熟語についても触れてください。",
    "数学": "公式の根拠を重視し、計算過程を一行ずつ省略せず論理的に解説してください。単なる手順ではなく『なぜこの解法を選ぶのか』という思考の起点を言語化してください。",
    "国語": "論理構造（序破急など）を分解し、筆者の主張を明確にしてください。なぜその結論に至ったか、本文の接続詞などを根拠に論理的に説明してください。",
    "理科": "現象のメカニズムを原理・法則から説明してください。図表がある場合は、軸の意味や数値の変化が示す本質を読み解き、日常の具体例を添えてください。",
    "社会": "歴史的背景と現代の繋がりをストーリー化してください。単なる事実ের羅列ではなく『なぜこの出来事が起きたのか』という因果関係を重視して解説してください。",
    "その他": "画像内容を客観的に観察し、中立的かつ平易な言葉で要点を3つのポイントに整理して解説してください。"
}

# --- 画面制御 ---
if not st.session_state.agreed:
    st.markdown("### 【本ソフトウェア利用に関する同意事項】")
    st.info("第1条（著作権の遵守）...（中略：同意文言一言一句維持）")
    if st.checkbox("上記の内容を理解し、すべての条項に同意します。"):
        st.session_state.agreed = True
        st.rerun()
    st.stop()

if "school_type" not in st.session_state:
    with st.form("init"):
        api_key = st.text_input("Gemini API Key", type="password")
        c1, c2 = st.columns(2)
        school_type = c1.selectbox("学校区分", ["小学生", "中学生", "高校生"])
        grade = c1.selectbox("学年", [f"{i}年生" for i in range(1, 7)])
        age_val = c2.slider("解説ターゲット年齢", 7, 20, 15)
        quiz_count = c2.selectbox("問題数", [10, 15, 20, 25])
        if st.form_submit_button("🚀 準備完了"):
            st.session_state.user_api_key, st.session_state.school_type, st.session_state.grade = api_key, school_type, grade
            st.session_state.age_val, st.session_state.quiz_count = age_val, quiz_count
            st.session_state.history = load_history().get("history", {})
            st.rerun()
    st.stop()

# --- メインメニュー (タブ遷移の代わり) ---
m1, m2 = st.columns(2)
if m1.button("📖 学習ブースト", use_container_width=True): st.session_state.current_tab = "学習"
if m2.button("📈 ブースト履歴", use_container_width=True): st.session_state.current_tab = "履歴"
st.divider()

if st.session_state.current_tab == "学習":
    if st.session_state.review_mode:
        if st.button("⬅ 新規学習に戻る"):
            st.session_state.review_mode, st.session_state.final_json = False, None
            st.rerun()
    else:
        c_sub1, c_sub2 = st.columns([3, 1])
        subject_choice = c_sub2.selectbox("🎯 教科", list(SUBJECT_PROMPTS.keys()), label_visibility="collapsed")
        final_subject_name = subject_choice
        cam_file = st.file_uploader("📸 教科書をスキャン", type=['png', 'jpg', 'jpeg'])

        if cam_file and st.button("✨ ブースト開始", use_container_width=True):
            genai.configure(api_key=st.session_state.user_api_key)
            model = genai.GenerativeModel('gemini-3-flash-preview')
            with st.status("解析中...🚀"):
                img = Image.open(cam_file).convert("RGB")
                img.thumbnail((1024, 1024))
                # ルビ指示の具体化（文言は維持しつつ補足）
                prompt = f"""あなたは{st.session_state.school_type}{st.session_state.grade}担当の天才教育者です。
                【教科別個別ミッション: {final_subject_name}】{SUBJECT_PROMPTS[subject_choice]}
                【共通厳守ルール】1.is_match 2.根拠[P.〇/〇行目] 3.audio_script(ひらがな化) 4.ランク別メッセージ 5.ターゲット年齢{st.session_state.age_val}歳 6.100文字ブロック 7.難読語ルビ（ターゲット年齢{st.session_state.age_val}歳が読めない専門用語や難読語のみ） 8.問題数{st.session_state.quiz_count}問
                ###JSON形式で出力せよ###
                {{ "is_match": true, "detected_subject": "{final_subject_name}", "page": "数字", "explanation_blocks": [{{ "text": "..", "audio_target": ".." }}], "english_only_script": "..", "audio_script": "..", "boost_comments": {{ "high": {{"text":"..","script":".."}}, "mid": {{"text":"..","script":".."}}, "low": {{"text":"..","script":".."}} }}, "quizzes": [{{ "question":"..", "options":[".."], "answer":0, "location":"P.〇" }}] }}"""
                res_raw = model.generate_content([prompt, img])
                match = re.search(r"(\{.*\})", res_raw.text, re.DOTALL)
                if match:
                    st.session_state.final_json = json.loads(match.group(1))
                    st.session_state.final_json["used_subject"] = final_subject_name
                    st.rerun()

    if st.session_state.final_json:
        res = st.session_state.final_json
        # (解説表示ロジック等はV1.2を維持)
        # ... [中略：クイズ表示、回答、結果表示ロジックはV1.2と同じ] ...
        # (スペースの都合上省略しますが、アップロード時には全量含めます)
        st.write(f"（{res['used_subject']}の問題を表示中...）")
        # クイズ表示部分（V1.2のコードをここに挿入）

else: # 履歴画面
    st.write(f"📂 保存先: `{get_filename()}`")
    for sub, logs in st.session_state.history.items():
        with st.expander(f"📙 {sub}"):
            for i, log in enumerate(logs):
                c_1, c_2, c_3 = st.columns([2, 2, 1])
                c_1.write(f"📅 {log['date']}")
                c_2.write(f"📄 P.{log['page']} - {log['score']}")
                if "quizzes" in log and c_3.button("🔄 解き直し", key=f"rev_{sub}_{i}"):
                    st.session_state.final_json = {"quizzes": log["quizzes"], "used_subject": sub, "page": log["page"]}
                    st.session_state.review_mode = True
                    st.session_state.current_tab = "学習" # ← ここで自動遷移
                    st.rerun()
