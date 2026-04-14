import os
from flask import Flask, request, jsonify
from flask_cors import CORS
from pymongo import MongoClient
import google.generativeai as genai
from dotenv import load_dotenv

# تحميل المتغيرات السرية من ملف .env
load_dotenv()

app = Flask(__name__)
CORS(app)

# -----------------------------------------
# إعداد الذكاء الاصطناعي (AI Setup)
# -----------------------------------------
API_KEY = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=API_KEY)
model = genai.GenerativeModel('gemini-pro')

def check_content_with_ai(text):
    """فحص النص بالذكاء الاصطناعي"""
    try:
        prompt = f"""
        أنت مشرف محتوى مصري حازم جداً في سيرفر ديسكورد محترم.
        مهمتك هي قراءة النص التالي وتحديد ما إذا كان يحتوي على أي شتائم، ألفاظ خارجة، إيحاءات، تنمر، أو كلمات غير لائقة.
        ابحث عن المخالفات باللغة العربية الفصحى، العامية المصرية الدارجة، الفرانكو، أو الإنجليزية.
        
        إذا كان النص محترماً وعادياً، أجب بكلمة واحدة فقط: مقبول
        إذا كان النص يحتوي على أي لفظ مسيء، أجب بكلمة واحدة فقط: مرفوض
        
        النص: "{text}"
        """
        response = model.generate_content(prompt)
        result = response.text.strip()
        return "مقبول" in result
    except Exception as e:
        print(f"AI Error: {e}")
        return False

# -----------------------------------------
# إعداد قاعدة بيانات MongoDB
# -----------------------------------------
MONGO_URI = os.getenv("MONGO_URI")
client = MongoClient(MONGO_URI)
db = client['victoria_db'] # اسم قاعدة البيانات
contributions_collection = db['contributions'] # اسم الـ Collection (الجدول)

# -----------------------------------------
# مسارات السيرفر (API Routes)
# -----------------------------------------

@app.route('/api/add_contribution', methods=['POST'])
def add_contribution():
    data = request.json
    username = data.get('username')
    contrib_type = data.get('type')
    content = data.get('content')

    if not content or not username:
        return jsonify({'error': 'بيانات ناقصة!'}), 400

    # 1. الفحص بالذكاء الاصطناعي
    is_clean = check_content_with_ai(content)
    
    if not is_clean:
        return jsonify({
            'status': 'rejected',
            'message': 'عذراً، النص يحتوي على كلمات غير لائقة أو مخالفة لقوانين السيرفر.'
        }), 406

    # 2. الحفظ في MongoDB
    new_contribution = {
        "username": username,
        "type": contrib_type,
        "content": content,
        "upvotes": 0
    }
    
    contributions_collection.insert_one(new_contribution)

    return jsonify({
        'status': 'success',
        'message': 'تم نشر مساهمتك بنجاح!'
    }), 201

@app.route('/api/get_contributions', methods=['GET'])
def get_contributions():
    # جلب البيانات من الأحدث للأقدم (_id يحتوي على الـ timestamp في MongoDB)
    contributions_cursor = contributions_collection.find().sort('_id', -1)
    
    contributions_list = []
    for item in contributions_cursor:
        contributions_list.append({
            'id': str(item['_id']), # تحويل الـ ObjectId لـ String عشان يتبعت كـ JSON
            'username': item.get('username'),
            'type': item.get('type'),
            'content': item.get('content'),
            'upvotes': item.get('upvotes', 0)
        })

    return jsonify(contributions_list), 200

if __name__ == '__main__':
    app.run(debug=True, port=5000)
