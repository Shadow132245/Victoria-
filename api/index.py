import os
from flask import Flask, request, jsonify
from flask_cors import CORS
from pymongo import MongoClient
import google.generativeai as genai

app = Flask(__name__)
CORS(app)

# إعداد الذكاء الاصطناعي
API_KEY = os.environ.get("GEMINI_API_KEY")
if API_KEY:
    genai.configure(api_key=API_KEY)
    model = genai.GenerativeModel('gemini-pro')

def check_content_with_ai(text):
    if not API_KEY:
        return True # لو مفيش مفتاح، هيقبل النص مؤقتاً عشان الموقع ميتعطلش
        
    try:
        prompt = f"""
        أنت مشرف محتوى مصري حازم جداً في سيرفر ديسكورد محترم.
        مهمتك هي قراءة النص وتحديد ما إذا كان يحتوي على شتائم، ألفاظ خارجة، إيحاءات، أو كلمات غير لائقة.
        
        إذا كان محترماً، أجب: مقبول
        إذا كان مسيئاً، أجب: مرفوض
        
        النص: "{text}"
        """
        response = model.generate_content(prompt)
        return "مقبول" in response.text.strip()
    except Exception as e:
        print(f"AI Error: {e}")
        return False

# إعداد MongoDB
MONGO_URI = os.environ.get("MONGO_URI")
if MONGO_URI:
    client = MongoClient(MONGO_URI)
    db = client['victoria_db']
    contributions_collection = db['contributions']

@app.route('/api/add_contribution', methods=['POST'])
def add_contribution():
    data = request.json
    username = data.get('username')
    contrib_type = data.get('type')
    content = data.get('content')

    if not content or not username:
        return jsonify({'error': 'بيانات ناقصة!'}), 400

    is_clean = check_content_with_ai(content)
    if not is_clean:
        return jsonify({
            'status': 'rejected',
            'message': 'عذراً، النص يحتوي على كلمات غير لائقة.'
        }), 406

    if MONGO_URI:
        contributions_collection.insert_one({
            "username": username,
            "type": contrib_type,
            "content": content,
            "upvotes": 0
        })

    return jsonify({'status': 'success', 'message': 'تم النشر بنجاح!'}), 201

@app.route('/api/get_contributions', methods=['GET'])
def get_contributions():
    if not MONGO_URI:
        return jsonify([])

    contributions_cursor = contributions_collection.find().sort('_id', -1)
    contributions_list = []
    
    for item in contributions_cursor:
        contributions_list.append({
            'id': str(item['_id']),
            'username': item.get('username'),
            'type': item.get('type'),
            'content': item.get('content'),
            'upvotes': item.get('upvotes', 0)
        })

    return jsonify(contributions_list), 200

# Vercel بيحتاج كائن app عشان يشتغل، فمش محتاجين app.run() هنا
