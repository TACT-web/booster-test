import streamlit as st
import google.generativeai as genai
from PIL import Image
import io, json, time, re, datetime, os

# --- 基本設定 ---
st.set_page_config(page_title="教科書ブースター V1.3 完全確定版", layout="centered", page_icon="🚀")

# --- セッション初期化 (全てのフラグ・状態を保持) ---
if "agreed" not in st.session_state: st.session_state.agreed = False
if "setup_completed" not in st.session_state: st.session_state.setup_completed = False
if "history" not in st.session_state: st.session_state.history = {}
if "final_json" not in st.session_state: st.session_state.final_json = None
if "font_size" not in st.session_state: st.session_state.font_size = 18
if "user_api_key" not in st.session_state: st.session_state.user_api_key = ""
if "voice_speed" not in st.session_state: st.session_state.voice_speed = 1.0
if "show_voice_btns" not in st.session_state: st.session_state.show_voice_btns = False

# --- 履歴管理 ---
def save_history(history):
    filename = f"history_{st.session_state.school_type}_{st.session_state.grade}.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

def load_history():
    filename = f"history_{st.session_state.school_type}_{st.session_state.grade}.json"
    if os.path.exists(filename):
        try:
            with open(filename, "r", encoding="utf-8") as f: return json.load(f)
        except: return {}
    return {}

# --- 音声再生エンジン (JavaScript) ---
def speak_js(text, speed=1.0, lang="ja-JP"):
    if text:
        safe_text = text.replace("'", "\\'").replace("\n", " ")
        js_code = f"""<script>
        var synth = window.parent.speechSynthesis;
        synth.cancel();
        var uttr = new SpeechSynthesisUtterance('{safe_text}');
        uttr.rate = {speed};
        uttr.lang = '{lang}';
        synth.speak(uttr);
        </script>"""
        st.components.v1.html(js_code, height=0)
    else:
        st.components.v1.html("<script>window.parent.speechSynthesis.cancel();</script>", height=0)

# --- 音声クレンジング関数 (修正版) ---
def get_clean_speech_text(text):
    if not text: return ""
    # 1. HTMLタグ（<br>など）を除去
    clean_text = re.sub(r'<[^>]+>', '', text)
    # 2. Markdownの太字（**）を削除
    clean_text = clean_text.replace('**', '')
    
    # 【修正】■を「しかく」と読むのを防ぐため削除
    clean_text = clean_text.replace('■', '').replace('●', '').replace('・', ' ')
    
    # 【修正】「12行目」などを「じゅうにごうめ」ではなく「ぎょうめ」と読ませる
    clean_text = re.sub(r'(\d+)行目', r'\1ぎょうめ', clean_text)
    
    # [cite_start]3. ルビ(括弧書き)を除去して二重読みを防ぐ
    clean_text = re.sub(r'\(.*?\)', '', clean_text)
    # 4. 英語のスラッシュ構文 :color[ / ] を「、」に置換
    clean_text = re.sub(r':[a-z]+\[\s*/\s*\]', '、', clean_text)
    # 5. ハッシュタグ、スラッシュ、表形式記号を削除して読み上げを綺麗にする
    clean_text = clean_text.replace('#', '').replace('/', '、').replace('|', '').replace('-', '')
    return clean_text.strip()

# --- 教科別プロンプト (修正版) ---
SUBJECT_PROMPTS = {
    "英語": """解説は必ず以下の【出力テンプレート】に従い、視認性を最優先して作成してください。

【出力テンプレート】
### ■ 凡例
- 🟢 **:green[ / ]** ： 主語・動詞の区切り<br>
- 🔵 **:blue[ / ]** ： 目的語の間（SVOO）<br>
- 🔴 **:red[ / ]** ： 補語の間（SVOC）<br>
- 🟡 **:orange[ / ]** ： 前置詞・修飾語の前<br>

### ■ 重要語句
| 単語 | 意味 | 単語 | 意味 |
| :--- | :--- | :--- | :--- |
| （例：uncle） | （例：叔父） | （例：watch） | （例：腕時計） |
※単語リストは必ずこの「4列のマークダウン表形式」で出力すること。

### ■ スラッシュ解説（最重要：必ず表形式を維持）
| 英文（構造可視化） | 意味の塊 | 理由・文法 |
| :--- | :--- | :--- |
| （例：I **:green[ / ]** am...） | （例：私は / ...） | （解説） |

【絶対ルール】
1. スラッシュは必ず太字記号で囲み **:color[ / ]** の形式にして、色を強調すること。
2. 凡例は各行の末尾に <br> を入れて、物理的に強制改行させること。
3. 全ての解説は必ず `|` 記号を使った「マークダウン表形式」を崩さずに出力すること。""",

    "数学": "公式の根拠を重視し、計算過程を一行ずつ省略せず論理的に解説してください。単なる手順ではなく『なぜこの解法を選ぶのか』という思考の起点を言語化してください。",
    
    "国語": "論理構造（序破急など）を分解し、筆者の主張を明確にしてください。なぜその結論に至ったか、本文の接続詞などを根拠に論理的に説明してください。",
    
    "理科": "【重要ルール：重要語句を最初に表記し、その後に解説を行うこと】現象のメカニズムを原理・法則から説明してください。図表がある場合は、軸の意味や数値の変化が示す本質を読み解き、日常の具体例を添えてください。",
    
    "社会": "【重要ルール：重要語句を最初に表記し、その後に解説を行うこと】歴史的背景と現代の繋がりをストーリー化してください。単なる事実の羅列ではなく『なぜこの出来事が起きたのか』という因果関係を重視して解説してください。",
    
    "その他": "画像内容を客観的に観察し、中立性かつ平易な言葉で要点を3つのポイントに整理して解説してください。"
}

# --- 1. 同意画面 ---
if not st.session_state.agreed:
    st.title("🚀 教科書ブースター V1.3")
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
            st.session_state.agreed = True
            st.rerun()
    st.stop()

# --- 2. 初期セットアップ ---
if not st.session_state.setup_completed:
    st.subheader("⚙️ 初期セットアップ")
    with st.form("setup_form"):
        st.session_state.user_api_key = st.text_input("Gemini API Key", type="password")
        c1, c2 = st.columns(2)
        st.session_state.school_type = c1.selectbox("学校区分", ["小学生", "中学生", "高校生"])
        st.session_state.grade = c1.selectbox("学年", [f"{i}年生" for i in range(1, 7)])
        st.session_state.age_val = c2.slider("解説ターゲット年齢", 7, 20, 15)
        st.session_state.quiz_count = c2.selectbox("問題数", [10, 15, 20, 25])
        if st.form_submit_button("🚀 学習を開始する"):
            st.session_state.history = load_history()
            st.session_state.setup_completed = True
            st.rerun()
    st.stop()

# --- サイドバー ---
st.sidebar.header("🛠️ クイック調整")
st.session_state.font_size = st.sidebar.slider("🔍 文字サイズ", 14, 45, st.session_state.font_size)
st.session_state.voice_speed = st.sidebar.slider("🐌 音声速度", 0.5, 2.0, st.session_state.voice_speed, 0.1)
st.session_state.user_api_key = st.sidebar.text_input("API Key 更新", value=st.session_state.user_api_key, type="password")

st.markdown(f"<style>.content-body {{ font-size: {st.session_state.font_size}px !important; line-height: 1.6; }}</style>", unsafe_allow_html=True)

# --- 3. メイン画面 (タブ管理) ---
tab_study, tab_history, tab_config = st.tabs(["📖 学習", "📈 履歴", "⚙️ 設定変更"])

with tab_config:
    with st.form("update_settings"):
        u_s_type = st.selectbox("学校区分", ["小学生", "中学生", "高校生"], index=["小学生", "中学生", "高校生"].index(st.session_state.school_type))
        u_grade = st.selectbox("学年", [f"{i}年生" for i in range(1, 7)], index=[f"{i}年生" for i in range(1, 7)].index(st.session_state.grade))
        u_age = st.slider("解説ターゲット年齢", 7, 20, st.session_state.age_val)
        u_q = st.selectbox("問題数", [10, 15, 20, 25], index=[10, 15, 20, 25].index(st.session_state.quiz_count))
        
        if st.form_submit_button("✅ 設定を更新"):
            st.session_state.school_type, st.session_state.grade = u_s_type, u_grade
            st.session_state.age_val, st.session_state.quiz_count = u_age, u_q
            st.session_state.history = load_history()
            st.toast("設定を保存しました")

with tab_history:
    st.write(f"📂 {st.session_state.school_type} {st.session_state.grade} の履歴")
    for sub, logs in st.session_state.history.items():
        with st.expander(f"📙 {sub}"):
            for log in logs: st.write(f"📅 {log['date']} | 結果: {log['score']}")

with tab_study:
    c_s1, c_s2 = st.columns(2)
    subject_choice = c_s1.selectbox("🎯 教科", list(SUBJECT_PROMPTS.keys()))
    style_choice = c_s2.selectbox("🎨 解説スタイル", ["定型", "対話形式", "ニュース風", "自由入力"])
    custom_style = st.text_input("カスタムスタイル指定", placeholder="例: 実況風") if style_choice == "自由入力" else ""

    cam_file = st.file_uploader("📸 教科書をスキャン", type=['png', 'jpg', 'jpeg'])

    if cam_file and st.button("✨ ブースト開始", use_container_width=True):
        if not st.session_state.user_api_key:
            st.error("APIキーを入力してください")
        else:
            genai.configure(api_key=st.session_state.user_api_key)
            model = genai.GenerativeModel('gemini-3-flash-preview')
            
            with st.status("教科書を分析中..."):
                style_inst = {"定型":"冷静な天才教育者","対話形式":"親しみやすい対話型の先生","ニュース風":"結論から伝えるニュース速報風","自由入力":custom_style}[style_choice]
                eng_opt = "英語なら冒頭に重要単語表を作成し、解説文はHTMLタグやMarkdownのカラー構文で視覚的にわかりやすく整理せよ。" if subject_choice == "英語" else ""

                # 【修正】クイズの出題範囲を解説内容に限定する強力な指示を追加
                full_prompt = f"""あなたは{st.session_state.school_type}{st.session_state.grade}担当。
【教科ミッション: {subject_choice}】{SUBJECT_PROMPTS[subject_choice]}
【ルール】1.is_match 2.根拠[P.〇/〇行目] 3.english_only_script(英語のみ) 4.年齢{st.session_state.age_val}歳 5.1ブロック100-200文字 6.問題数{st.session_state.quiz_count}
【クイズ厳守事項】問題(quizzes)は、必ず「explanation_blocks」で実際に解説した内容のみから作成すること。解説にない知識を問うことは禁止。
【スタイル】{style_inst} 【構成】導入サマリー → 詳細解説。※クイズは専用のJSONフィールドにのみ出力せよ。{eng_opt}

###JSON形式で出力せよ###
{{ 
  "is_match": true, 
  "detected_subject": "{subject_choice}", 
  "page": "数字", 
  "explanation_blocks": [{{ "text": "表示と読み上げに使われる解説文" }}], 
  "english_only_script": "英文のみのテキスト", 
  "boost_comments": {{ 
    "high": {{"text":"正解時の励まし","script":"読み上げ台本"}}, 
    "mid": {{"text":"まずまずの時の励まし","script":"読み上げ台本"}}, 
    "low": {{"text":"苦戦時の励まし","script":"読み上げ台本"}} 
  }}, 
  "quizzes": [{{ "question":"..", "options":[".."], "answer":0 }}] 
}}""" 
                
                img = Image.open(cam_file)
                res_raw = model.generate_content([full_prompt, img])
                match = re.search(r"(\{.*\})", res_raw.text, re.DOTALL)
                if match:
                    st.session_state.final_json = json.loads(match.group(1))
                    st.session_state.final_json["used_subject"] = subject_choice

if st.session_state.final_json:
    res = st.session_state.final_json
    v_cols = st.columns([1, 1, 1, 1])
    with v_cols[0]:
        if st.button("🔊 全文再生"):
            full_text = " ".join([b["text"] for b in res.get("explanation_blocks", [])])
            speak_js(get_clean_speech_text(full_text), st.session_state.voice_speed, "ja-JP")
    with v_cols[1]:
        if res.get("used_subject") == "英語" and st.button("🔊 英文のみ再生"):
            speak_js(res.get("english_only_script"), st.session_state.voice_speed, "en-US")
    with v_cols[2]:
        if st.button("🛑 停止"): speak_js("")
    with v_cols[3]:
        if st.button("🔊 個別再生"):
            st.session_state.show_voice_btns = not st.session_state.show_voice_btns
            st.rerun()

    for i, block in enumerate(res.get("explanation_blocks", [])):
        with st.container(border=True):
            st.markdown(f'<div class="content-body">{block["text"]}</div>', unsafe_allow_html=True)
            if st.session_state.show_voice_btns:
                if st.button(f"▶ 再生", key=f"v_{i}"):
                    lang = "en-US" if res.get("used_subject") == "英語" else "ja-JP"
                    clean_voice = get_clean_speech_text(block["text"])
                    speak_js(clean_voice, st.session_state.voice_speed, lang)

    with st.expander("📝 定着確認クイズ", expanded=True):
        score = 0
        for i, q in enumerate(res.get("quizzes", [])):
            ans = st.radio(f"問{i+1}: {q['question']}", q['options'], key=f"q_{i}", index=None)
            if ans == q['options'][q['answer']]: score += 1
        if st.button("採点 & 保存"):
            rate = (score / len(res["quizzes"])) * 100
            st.metric("正解率", f"{rate:.0f}%")
            rank = "high" if rate == 100 else "mid" if rate >= 50 else "low"
            st.info(res["boost_comments"][rank]["text"])
            speak_js(res["boost_comments"][rank]["script"], st.session_state.voice_speed)
            subj = res.get("used_subject", "不明")
            if subj not in st.session_state.history: st.session_state.history[subj] = []
            st.session_state.history[subj].append({"date": datetime.datetime.now().strftime("%m-%d %H:%M"), "score": f"{rate:.0f}%"})
            save_history(st.session_state.history)
