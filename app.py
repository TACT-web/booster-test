import streamlit as st
import google.generativeai as genai
from PIL import Image
import io, json, time, re, datetime, gc, os

# --- 基本設定 ---
st.set_page_config(page_title="教科書ブースター V1.2", layout="centered", page_icon="🚀")

# --- 🛠️ 履歴の自動永続化ロジック (UX強化版) ---
def get_all_history_files():
    """保存されている学年別ファイルをすべて取得"""
    return [f for f in os.listdir() if f.startswith("history_") and f.endswith(".json")]

def load_history_by_file(filename):
    if os.path.exists(filename):
        try:
            with open(filename, "r", encoding="utf-8") as f:
                return json.load(f)
        except: return {}
    return {}

def save_history(history):
    filename = f"history_{st.session_state.school_type}_{st.session_state.grade}.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

# --- セッション初期化 ---
if "current_tab" not in st.session_state: st.session_state.current_tab = "学習"
if "history" not in st.session_state: st.session_state.history = {}
if "final_json" not in st.session_state: st.session_state.final_json = None
if "agreed" not in st.session_state: st.session_state.agreed = False
if "font_size" not in st.session_state: st.session_state.font_size = 18
if "show_voice_btns" not in st.session_state: st.session_state.show_voice_btns = False
if "review_mode" not in st.session_state: st.session_state.review_mode = False
if "user_api_key" not in st.session_state: st.session_state.user_api_key = ""

# --- リロード時の自動復元ロジック ---
if not st.session_state.agreed:
    files = get_all_history_files()
    if files:
        latest_file = max(files, key=os.path.getmtime)
        saved_data = load_history_by_file(latest_file)
        if saved_data:
            parts = latest_file.replace(".json", "").split("_")
            if len(parts) == 3:
                st.session_state.agreed = True
                st.session_state.school_type = parts[1]
                st.session_state.grade = parts[2]
                st.session_state.history = saved_data
                st.session_state.current_tab = "履歴"

def speak_chrome(text, speed=1.0, lang="ja-JP"):
    if text:
        safe_text = text.replace("'", "\\'").replace("\n", " ")
        js_code = f"<script>var synth = window.parent.speechSynthesis; synth.cancel(); var uttr = new SpeechSynthesisUtterance('{safe_text}'); uttr.rate = {speed}; uttr.lang = '{lang}'; synth.speak(uttr);</script>"
        st.components.v1.html(js_code, height=0)

def stop_speech():
    st.components.v1.html("<script>window.parent.speechSynthesis.cancel();</script>", height=0)

st.markdown(f"<style>.content-body {{ font-size: {st.session_state.font_size}px !important; line-height: 1.6; }}</style>", unsafe_allow_html=True)

# 教科別個別プロンプト (一言一句維持)
SUBJECT_PROMPTS = {
    "英語": "英文を意味の塊（/）で区切るスラッシュリーディング形式（英文 / 訳）を徹底してください。重要な文法構造や熟語についても触れてください。",
    "数学": "公式の根拠を重視し、計算過程を一行ずつ省略せず論理的に解説してください。単なる手順ではなく『なぜこの解法を選ぶのか』という思考の起点を言語化してください。",
    "国語": "論理構造（序破急など）を分解し、筆者の主張を明確にしてください。なぜその結論に至ったか、本文の接続詞などを根拠に論理的に説明してください。",
    "理科": "現象のメカニズムを原理・法則から説明してください。図表がある場合は、軸の意味や数値の変化が示す本質を読み解き、日常の具体例を添えてください。",
    "社会": "歴史的背景と現代の繋がりをストーリー化してください。単なる事実の羅列ではなく『なぜこの出来事が起きたのか』という因果関係を重視して解説してください。",
    "その他": "画像内容を客観的に観察し、中立的かつ平易な言葉で要点を3つのポイントに整理して解説してください。"
}

# 1. 同意画面 (文言完全維持)
if not st.session_state.agreed:
    st.markdown("""<div style="line-height: 1.1; margin-bottom: 20px;"><span style="font-size: 24px; font-weight: bold; white-space: nowrap;">🚀教科書ブースター</span><br><span style="font-size: 14px; color: gray;">Ver 1.2</span></div>""", unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown("""
        ### 【本ソフトウェア利用に関する同意事項】
        **第1条（著作権の遵守）**
        利用者は、本アプリで取り扱う教科書等の著作物が著作権法により保護されていることを認識し、解析結果等を権利者の許可なく第三者に公開（SNS、ブログ等への掲載）してはならないものとします。
        **第2条（AI生成物の正確性と免責）**
        本アプリが提供する解説および回答は、人工知能による推論に基づくものであり、その正確性、完全性、妥当性を保証するものではありません。生成された内容に起因する学習上の不利益や損害について、開発者は一切の責任を負いません。
        **第3条（利用目的）**
        本アプリは利用者の私的な学習補助を目的として提供されるものです。試験等の最終的な確認は、必ず公式な教材および指導者の指示に従ってください。
        """)
        if st.checkbox("上記の内容を理解し、すべての条項に同意します。"):
            st.session_state.agreed = True; st.rerun()
    st.stop()

# 2. 設定画面 (APIキーなしでも履歴は見れるように)
if "school_type" not in st.session_state:
    with st.form("settings"):
        st.info("過去の履歴を見るだけならAPIキーは空でOKです。")
        api_key = st.text_input("Gemini API Key", type="password")
        c1, c2 = st.columns(2)
        s_type = c1.selectbox("学校区分", ["小学生", "中学生", "高校生"])
        grade = c1.selectbox("学年", [f"{i}年生" for i in range(1, 7)])
        age_val = c2.slider("解説ターゲット年齢", 7, 20, 15)
        q_count = c2.selectbox("問題数", [10, 15, 20, 25])
        if st.form_submit_button("🚀 準備完了"):
            st.session_state.user_api_key, st.session_state.school_type, st.session_state.grade = api_key, s_type, grade
            st.session_state.age_val, st.session_state.quiz_count = age_val, q_count
            st.session_state.history = load_history_by_file(f"history_{s_type}_{grade}.json")
            st.rerun()
    st.stop()

# 3. メインナビゲーション (タブの自動遷移用)
m1, m2 = st.columns(2)
if m1.button("📖 学習ブースト", use_container_width=True): st.session_state.current_tab = "学習"
if m2.button("📈 ブースト履歴", use_container_width=True): st.session_state.current_tab = "履歴"
st.divider()

if st.session_state.current_tab == "学習":
    if st.session_state.review_mode:
        st.info("🔄 復習モード中（過去の問題を解いています）")
        if st.button("⬅ 新規学習に戻る"):
            st.session_state.review_mode, st.session_state.final_json = False, None
            st.rerun()
    else:
        st.session_state.user_api_key = st.sidebar.text_input("API Key設定", value=st.session_state.user_api_key, type="password")
        c_sub1, c_sub2 = st.columns([3, 1])
        with c_sub1: st.markdown(f"### 📖 {st.session_state.school_type} {st.session_state.grade}")
        subject_choice = c_sub2.selectbox("🎯 教科", list(SUBJECT_PROMPTS.keys()), label_visibility="collapsed")
        cam_file = st.file_uploader("📸 教科書をスキャン", type=['png', 'jpg', 'jpeg'])

        if cam_file and st.button("✨ ブースト開始", use_container_width=True):
            if not st.session_state.user_api_key: st.error("解析にはAPIキーが必要です。サイドバーで設定してください。")
            else:
                genai.configure(api_key=st.session_state.user_api_key)
                model = genai.GenerativeModel('gemini-3-flash-preview')
                with st.status("解析中...🚀"):
                    img = Image.open(cam_file).convert("RGB")
                    img.thumbnail((1024, 1024))
                    prompt = f"""あなたは{st.session_state.school_type}{st.session_state.grade}担当の天才教育者です。
                    【教科別個別ミッション: {subject_choice}】{SUBJECT_PROMPTS[subject_choice]}
                    【共通厳守ルール】1.is_match 2.根拠[P.〇/〇行目] 3.audio_script(ひらがな化) 4.ランク別メッセージ 5.ターゲット年齢{st.session_state.age_val}歳 6.100文字ブロック 7.難読語ルビ（ターゲット年齢{st.session_state.age_val}歳が読めない専門用語や難読語のみに絞ること） 8.問題数{st.session_state.quiz_count}問
                    ###JSON形式で出力せよ###
                    {{ "is_match": true, "detected_subject": "{subject_choice}", "page": "数字", "explanation_blocks": [{{ "text": "..", "audio_target": ".." }}], "english_only_script": "..", "audio_script": "..", "boost_comments": {{ "high": {{"text":"..","script":".."}}, "mid": {{"text":"..","script":".."}}, "low": {{"text":"..","script":".."}} }}, "quizzes": [{{ "question":"..", "options":[".."], "answer":0, "location":"P.〇" }}] }}"""
                    res_raw = model.generate_content([prompt, img])
                    match = re.search(r"(\{.*\})", res_raw.text, re.DOTALL)
                    if match:
                        st.session_state.final_json = json.loads(match.group(1))
                        st.session_state.final_json["used_subject"] = subject_choice
                        st.rerun()

    if st.session_state.final_json:
        res = st.session_state.final_json
        if not st.session_state.review_mode:
            st.session_state.font_size = st.sidebar.slider("🔍 文字サイズ", 14, 45, st.session_state.font_size)
            speed = st.sidebar.slider("🐌 音声速度", 0.5, 2.0, 1.0, 0.1)
            v_cols = st.columns(4 if res.get("used_subject") == "英語" else 3)
            with v_cols[0]:
                if st.button("🔊 全文"): speak_chrome(res.get("audio_script"), speed)
            if res.get("used_subject") == "英語":
                with v_cols[1]:
                    if st.button("🔊 英文"): speak_chrome(res.get("english_only_script", ""), speed, "en-US")
            with v_cols[-2]:
                if st.button("🛑 停止"): stop_speech()
            with v_cols[-1]:
                if st.button("🔊 個別"):
                    st.session_state.show_voice_btns = not st.session_state.show_voice_btns; st.rerun()

            for i, block in enumerate(res.get("explanation_blocks", [])):
                with st.container(border=True):
                    st.markdown(f'<div class="content-body">{block["text"].replace("\\n", "<br>")}</div>', unsafe_allow_html=True)
                    if st.session_state.show_voice_btns:
                        if st.button(f"▶ 再生", key=f"v_{i}"):
                            speak_chrome(block["audio_target"], speed, "en-US" if res["used_subject"]=="英語" else "ja-JP")
        else:
            st.warning("【復習モード】過去の問題を表示しています。")

        st.subheader("📝 ブースト・チェック")
        user_page = st.text_input("📖 ページ確認", value=res.get("page", ""), disabled=st.session_state.review_mode)
        score, answered = 0, 0
        for i, q in enumerate(res.get("quizzes", [])):
            ans = st.radio(f"問{i+1}: {q['question']} ({q.get('location','')})", q['options'], key=f"q_{i}_{st.session_state.review_mode}", index=None)
            if ans:
                answered += 1
                if ans == q['options'][q['answer']]: st.success("⭕ 正解！"); score += 1
                else: st.error(f"❌ 正解: {q['options'][q['answer']]}")

        if answered == len(res.get("quizzes", [])) and len(res.get("quizzes", [])) > 0:
            if st.button("🏁 結果を記録"):
                rate = (score / len(res["quizzes"])) * 100
                st.header(f"スコア: {rate:.0f}%")
                if not st.session_state.review_mode:
                    rank = "high" if rate == 100 else "mid" if rate >= 50 else "low"
                    st.info(res["boost_comments"][rank]["text"])
                    speak_chrome(res["boost_comments"][rank]["script"])
                    subj = res["used_subject"]
                    if subj not in st.session_state.history: st.session_state.history[subj] = []
                    st.session_state.history[subj].append({"date": datetime.datetime.now().strftime("%m/%d %H:%M"), "page": user_page, "score": f"{rate:.0f}%", "quizzes": res["quizzes"]})
                    save_history(st.session_state.history); st.toast("履歴に保存しました！")

else: # 履歴画面
    st.write(f"📂 表示中の学年: {st.session_state.school_type} {st.session_state.grade}")
    for sub, logs in st.session_state.history.items():
        with st.expander(f"📙 {sub}"):
            for i, log in enumerate(logs):
                c1, c2, c3 = st.columns([2, 1, 1])
                c1.write(f"📅 {log['date']} (P.{log.get('page','?')})")
                c2.write(f"🏆 {log['score']}")
                if c3.button("🔄 解き直し", key=f"rev_{sub}_{i}"):
                    st.session_state.final_json = {"quizzes": log["quizzes"], "used_subject": sub}
                    st.session_state.review_mode = True
                    st.session_state.current_tab = "学習" # 学習画面へ自動遷移
                    st.rerun()
