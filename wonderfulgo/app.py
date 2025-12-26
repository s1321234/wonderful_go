import os
import json
import requests
import re
import time
import random
from dotenv import load_dotenv
from flask import Flask, render_template, request, jsonify

load_dotenv()
app = Flask(__name__)

api_key = os.getenv("GOOGLE_API_KEY")
if not api_key:
    print("【エラー】GOOGLE_API_KEY設定なし")

# ==========================================
# ★モデル設定
# ==========================================
MODEL_1 = "gemini-2.5-flash-lite"
MODEL_2 = "gemini-2.5-flash"
MODEL_3 = "gemini-2.0-flash" 

@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")

@app.route("/chat", methods=["POST"])
def chat():
    if not api_key: return jsonify({"error": "APIキーなし"}), 500

    data = request.json
    pet_info = data.get("petInfo", {})
    user_message = data.get("message", "")
    history = data.get("history", []) # フロントエンドからの履歴
    
    if not user_message: return jsonify({"error": "空のメッセージ"}), 400

    # モード判定
    is_planning = any(k in user_message for k in ["プラン", "コース", "ルート", "日程"]) and ("作って" in user_message or "提案" in user_message)
    
    # --- 1. プロンプト作成（ここを強化） ---
    # 犬の詳細プロフィールの構築
    pet_profile = "【愛犬の詳細プロファイル】\n"
    labels = {
        "dog_name":"名前","breed":"犬種","gender":"性別","age":"年齢","weight":"体重",
        "personality":"性格","owner_residence":"居住地","dog_interaction":"他の犬との交流",
        "human_interaction":"人との交流","medical_history":"持病","allergies":"アレルギー",
        "exercise_level":"運動量","car_sickness":"車酔い","barking_tendency":"吠え癖","biting_habit":"噛み癖",
        "walk_frequency_time":"散歩の頻度","likes_water_play":"水遊びの好き嫌い","training_status":"しつけ状況"
    }
    for k, v in pet_info.items():
        if v and k in labels:
            pet_profile += f"- {labels[k]}: {v}\n"

    # 会話履歴のテキスト化
    chat_context = ""
    if history:
        chat_context = "【これまでの会話履歴】\n"
        for msg in history[-8:]: # 直近8件分
            role_name = "ユーザー" if msg['sender'] == 'user' else "AI"
            chat_context += f"{role_name}: {msg['content']}\n"
        chat_context += "--- 履歴ここまで ---\n\n"

    # ベースプロンプトの組み立て
    # 役割、犬情報、履歴、そして今回のメッセージ（要望含む）を統合
    prompt = "役割:犬の専門家。以下のプロファイルと履歴を把握し、犬種特性・性格・健康状態・ユーザーの今日の気分を考慮して回答せよ。挨拶不要。\n"
    prompt += f"{pet_profile}\n"
    prompt += f"{chat_context}"
    prompt += f"【今回の依頼・今日の気分・要望】\n{user_message}\n"

    # --- 2. ここからは「一切変えない」と指定されたブロック ---
    if is_planning:
        prompt += "\n※お出かけプラン作成\n"
        if "1日" in user_message: prompt += "条件:所要時間1日(3-4箇所,食事を含めたフルコース)\n"
        elif "半日" in user_message: prompt += "条件:所要時間半日(2-3箇所)\n"
        elif "2時間" in user_message: prompt += "条件:所要時間2時間(1-2箇所,散歩主体)\n"
        
        # 検索を使うので「実在の場所」を強く意識させる
        prompt += "Google検索で確認し、現在実在する場所のみを提案してください。JSON出力のみ:\n"
        prompt += '{"plan_title":"","greeting_message":"","spots":[{"name":"","address":"","pet_condition":"","description":""}]}'
    else:
        prompt += "回答はテキストのみ。"

    # --- AI通信 ---
    def call_gemini(model):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        
        # 基本のペイロード
        payload = {
            "contents": [{"parts": [{"text": prompt}]}]
        }

        # ★★★ ここが切り替えポイント！ ★★★
        # プラン作成モード(is_planning)の時だけ、Google検索ツールを追加する
        if is_planning:
            payload["tools"] = [{"google_search": {}}]
            print(f"📡 Connecting to {model} (With Search Mode)...")
        else:
            print(f"📡 Connecting to {model} (Text Only Mode)...")

        try:
            res = requests.post(url, headers={"Content-Type": "application/json"}, json=payload, timeout=60)
            
            if res.status_code == 200:
                return res.json()
            
            # エラー時
            print(f"⚠️ {model} Failed! Status: {res.status_code}")
            return None

        except Exception as e: 
            print(f"❌ Connection Error: {e}")
            return None
    # --- 指定ブロックここまで ---

    # リトライ処理
    result = None
    models = [MODEL_1, MODEL_2, MODEL_3]
    
    for i, model in enumerate(models):
        result = call_gemini(model)
        if result: break
        
        if i < len(models) - 1:
            time.sleep(2) # リトライ待機

    if not result:
        return jsonify({"error": "現在アクセスが集中しています。しばらく待ってから再試行してください。"}), 503

    # 結果処理
    try:
        if not result.get('candidates'): return jsonify({"response": "回答を生成できませんでした。"}), 200
        text = result['candidates'][0]['content']['parts'][0]['text']
        
        if is_planning:
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                try:
                    return jsonify(json.loads(match.group()))
                except: pass
        
        return jsonify({"response": text})

    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"error": "処理エラー"}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)