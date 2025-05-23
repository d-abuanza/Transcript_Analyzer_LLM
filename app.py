from flask import Flask, render_template, request
import os
import docx2txt
from langchain_google_genai import ChatGoogleGenerativeAI
import json
import re
import logging
from tenacity import retry, stop_after_attempt, wait_fixed

app = Flask(__name__)
logging.info("Flask uygulaması başarıyla başlatıldı")

# Günlük kaydı için ayar
logging.basicConfig(level=logging.DEBUG)

# Yüklenen dosyalar için klasör
UPLOAD_FOLDER = 'backend/uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Google AI API anahtarını yükle
from dotenv import load_dotenv
load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
if not GOOGLE_API_KEY:
    logging.error("Google API anahtarı bulunamadı!")
    raise ValueError("Google API anahtarı .env dosyasında mevcut değil")
logging.info("Google API anahtarı başarıyla yüklendi")

# Gemini API istemcisini kur
llm = ChatGoogleGenerativeAI(
    model="gemini-1.5-flash",
    google_api_key=GOOGLE_API_KEY,
    temperature=0,
    max_tokens=4000
)
logging.info("Google Gemini istemcisi başarıyla başlatıldı")

# Çıkarılan metni temizleme fonksiyonu
def clean_text(text):
    text = re.sub(r'\s+', ' ', text.strip())
    text = re.sub(r'[^\w\s\d\.\:\*\-]', '', text)
    return text

# Metinden dersleri manuel olarak çıkarma fonksiyonu
def extract_courses_from_text(text):
    courses_by_semester = {}
    current_semester = None
    lines = text.split('\n')
    for line in lines:
        line = line.strip()
        # Check if the line indicates a semester
        if re.match(r'^\d+\.\s*Yarıyıl$', line):
            current_semester = line
            if current_semester not in courses_by_semester:
                courses_by_semester[current_semester] = []
        # Check if the line is a course
        elif current_semester and re.match(r'^(BM|MTH|US|MS|AIB|TDB|FIZ|MAT|ING|KRP)\d{3}\s+', line):
            parts = line.split()
            if len(parts) >= 5:  # Ders kodu, adı (birden fazla kelime), kredi, AKTS, harf notu
                code = parts[0]  # Ders kodu (örneğin, "BM430", "US201", "MS301")
                grade = parts[-1]  # Harf notu (örneğin, "BB", "FF")
                # Ders adı, kredi ve AKTS arasındaki kısmı al
                name_parts = parts[1:-3]
                name = " ".join(name_parts)
                courses_by_semester[current_semester].append({
                    "code": code,
                    "name": name,
                    "grade": grade
                })
    return courses_by_semester

# Gemini API'den gelen derslerle manuel çıkarılan dersleri birleştirme
def merge_extracted_courses(extracted_data, manual_courses):
    for semester in extracted_data["semesters"]:
        semester_name = semester["semester"]
        if semester_name in manual_courses:
            # Gemini API'nin çıkardığı ders kodlarını al
            gemini_course_codes = {course["code"] for course in semester["courses"]}
            # Manuel olarak çıkarılan derslerden eksik olanları ekle
            for course in manual_courses[semester_name]:
                if course["code"] not in gemini_course_codes:
                    semester["courses"].append(course)
                    logging.debug(f"Eksik ders eklendi: {semester_name} - {course['code']}")
    return extracted_data

# 7. ve 8. yarıyıllarda tamamlanan seçmeli ders sayısını hesaplama
def count_completed_electives(semesters):
    elective_courses = []
    excluded_courses = []
    all_elective_courses = []  # Tüm seçmeli dersleri takip etmek için
    for semester in semesters:
        if semester["semester"] in ["7. Yarıyıl", "8. Yarıyıl"]:
            for course in semester["courses"]:
                if course["code"] in ["BM401", "BM499", "BM498"]:
                    excluded_courses.append((course["code"], "Zorunlu ders"))
                    continue
                if course["code"].startswith("BM") or course["code"].startswith("MTH"):
                    all_elective_courses.append(course["code"])  # Tüm seçmeli dersleri kaydet
                    if course["grade"] not in ["FF", "FD"]:
                        elective_courses.append(course)
                    else:
                        excluded_courses.append((course["code"], f"Başarısız not: {course['grade']}"))
    logging.debug(f"Tüm seçmeli dersler (7. ve 8. Yarıyıl): {all_elective_courses}")
    logging.debug(f"Tamamlanan seçmeli dersler: {[course['code'] for course in elective_courses]}")
    logging.debug(f"Hariç tutulan dersler: {excluded_courses}")
    return len(elective_courses)

# Her yarıyıl için zorunlu derslerin listesi
MANDATORY_COURSES = {
    "1. Yarıyıl": [
        {"code": "AIB101", "name": "Atatürk İlkeleri ve İnkılap Tarihi I"},
        {"code": "TDB121", "name": "Türk Dili I"},
        {"code": "FIZ101", "name": "Fizik I"},
        {"code": "BM107", "name": "Elektrik Devre Temelleri"},
        {"code": "MAT101", "name": "Matematik I"},
        {"code": "BM103", "name": "Bilgisayar Mühendisliğine Giriş"},
        {"code": "BM105", "name": "Bilişim Teknolojileri"},
        {"code": "BM101", "name": "Algoritmalar ve Programlama I"},
        {"code": "ING101", "name": "İngilizce I"}
    ],
    "2. Yarıyıl": [
        {"code": "AIB102", "name": "Atatürk İlkeleri ve İnkılap Tarihi II"},
        {"code": "TDB122", "name": "Türk Dili II"},
        {"code": "FIZ102", "name": "Fizik II"},
        {"code": "MAT102", "name": "Matematik II"},
        {"code": "BM102", "name": "Algoritmalar ve Programlama II"},
        {"code": "BM104", "name": "Web Teknolojileri"},
        {"code": "BM106", "name": "Olasılık ve İstatistik"},
        {"code": "KRP102", "name": "Kariyer Planlama"},
        {"code": "ING102", "name": "İngilizce II"}
    ],
    "3. Yarıyıl": [
        {"code": "BM211", "name": "Diferansiyel Denklemler"},
        {"code": "BM213", "name": "Lineer Cebir"},
        {"code": "BM205", "name": "Nesneye Dayalı Programlama"},
        {"code": "BM209", "name": "Sayısal Analiz"},
        {"code": "BM203", "name": "Elektronik"},
        {"code": "BM215", "name": "Ayrık İşlemsel Yapılar"}
    ],
    "4. Yarıyıl": [
        {"code": "BM204", "name": "Bilgisayar Organizasyonu"},
        {"code": "BM206", "name": "Sayısal Elektronik"},
        {"code": "BM208", "name": "Nesneye Dayalı Analiz ve Tasarım"},
        {"code": "BM210", "name": "Programlama Dillerinin Prensipleri"},
        {"code": "BM212", "name": "Mesleki İngilizce"},
        {"code": "BM214", "name": "Veri Yapıları"}
    ],
    "5. Yarıyıl": [
        {"code": "BM301", "name": "Biçimsel Diller ve Soyut Makinalar"},
        {"code": "BM303", "name": "İşaretler ve Sistemler"},
        {"code": "BM305", "name": "İşletim Sistemleri"},
        {"code": "BM307", "name": "Bilgisayar Ağları I"},
        {"code": "BM309", "name": "Veritabanı Yönetim Sistemleri"},
        {"code": "BM399", "name": "Yaz Dönemi Stajı I"}
    ],
    "6. Yarıyıl": [
        {"code": "BM302", "name": "Bilgisayar Ağları II"},
        {"code": "BM304", "name": "Mikroişlemciler"},
        {"code": "BM306", "name": "Sistem Programlama"},
        {"code": "BM308", "name": "Web Programlama"},
        {"code": "BM310", "name": "Yazılım Mühendisliği"}
    ],
    "7. Yarıyıl": [
        {"code": "BM401", "name": "Bilgisayar Mühendisliği Proje Tasarımı"},
        {"code": "BM499", "name": "Yaz Dönemi Stajı II"}
    ],
    "8. Yarıyıl": [
        {"code": "BM498", "name": "Mezuniyet Tezi"}
    ]
}

# قائمة الدروس الاختيارية
ELECTIVE_COURSES = {
    "3. Yarıyıl": [
        {"code": "US201", "name": "Bilim Tarihi ve Felsefesi"},
        {"code": "US207", "name": "Girişimcilik"},
        {"code": "US211", "name": "İş Psikolojisi"},
        {"code": "US213", "name": "İşletme Yönetimi"},
        {"code": "US215", "name": "Kültür Tarihi"},
        {"code": "US217", "name": "Sanat Tarihi"},
        {"code": "US219", "name": "Sivil Toplum Organizasyonları"},
        {"code": "US221", "name": "Uygarlık Tarihi"},
        {"code": "US225", "name": "Girişimcilik I"},
        {"code": "US227", "name": "Girişimcilik II"},
        {"code": "US203", "name": "Çevre ve Enerji"},
        {"code": "US209", "name": "İletişim Tekniği"},
        {"code": "US205", "name": "Davranış Bilimine Giriş"}
    ],
    "4. Yarıyıl": [
        {"code": "US201", "name": "Bilim Tarihi ve Felsefesi"},
        {"code": "US207", "name": "Girişimcilik"},
        {"code": "US211", "name": "İş Psikolojisi"},
        {"code": "US213", "name": "İşletme Yönetimi"},
        {"code": "US215", "name": "Kültür Tarihi"},
        {"code": "US217", "name": "Sanat Tarihi"},
        {"code": "US219", "name": "Sivil Toplum Organizasyonları"},
        {"code": "US221", "name": "Uygarlık Tarihi"},
        {"code": "US225", "name": "Girişimcilik I"},
        {"code": "US227", "name": "Girişimcilik II"},
        {"code": "US203", "name": "Çevre ve Enerji"},
        {"code": "US209", "name": "İletişim Tekniği"},
        {"code": "US205", "name": "Davranış Bilimine Giriş"}
    ],
    "5. Yarıyıl": [
        {"code": "MS301", "name": "Endüstri İlişkileri"},
        {"code": "MS303", "name": "Meslek Hastalıkları"},
        {"code": "MS305", "name": "Teknoloji Felsefesi"},
        {"code": "MS307", "name": "Mühendisler İçin Yönetim"},
        {"code": "MS309", "name": "Mühendislik Etiği"},
        {"code": "MS311", "name": "Kalite Yönetim Sistemleri ve Uygulaması"},
        {"code": "MS313", "name": "Toplam Kalite Yönetimi"},
        {"code": "MS315", "name": "İş Güvenliği"},
        {"code": "MS317", "name": "İş Hukuku"},
        {"code": "MS319", "name": "Mühendislik Ekonomisi"},
        {"code": "MS321", "name": "Bilişim Teknolojilerinde Yeni Gelişmeler"},
        {"code": "MS323", "name": "Betik Dilleri"},
        {"code": "MS332", "name": "Bilimsel Araştırma ve Rapor Yazma"}
    ],
    "6. Yarıyıl": [
        {"code": "MS301", "name": "Endüstri İlişkileri"},
        {"code": "MS303", "name": "Meslek Hastalıkları"},
        {"code": "MS305", "name": "Teknoloji Felsefesi"},
        {"code": "MS307", "name": "Mühendisler İçin Yönetim"},
        {"code": "MS309", "name": "Mühendislik Etiği"},
        {"code": "MS311", "name": "Kalite Yönetim Sistemleri ve Uygulaması"},
        {"code": "MS313", "name": "Toplam Kalite Yönetimi"},
        {"code": "MS315", "name": "İş Güvenliği"},
        {"code": "MS317", "name": "İş Hukuku"},
        {"code": "MS319", "name": "Mühendislik Ekonomisi"},
        {"code": "MS321", "name": "Bilişim Teknolojilerinde Yeni Gelişmeler"},
        {"code": "MS323", "name": "Betik Dilleri"},
        {"code": "MS331", "name": "Mühendislikte Temel Bilgiler"}
    ]
}

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload():
    if 'file' not in request.files:
        return "Dosya seçilmedi!", 400
    file = request.files['file']
    if file.filename == '':
        return "Dosya seçilmedi!", 400
    if file and file.filename.lower().endswith('.docx'):
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
        file.save(file_path)

        # .docx dosyasından metni çıkar
        text = docx2txt.process(file_path)
        text = clean_text(text)
        logging.debug(f"Çıkarılmış metin: {text}")

        # Gemini API için prompt hazırlığı
        prompt = f"""
        Akademik transkriptleri analiz eden yardımcı bir asistansınız. Aşağıdaki transkript metnine göre aşağıdaki adımları gerçekleştirin:

        ### Görev:
        1. Transkriptten tüm dersleri ve notlarını yarıyıl bazında çıkar.
        2. Her yarıyıl için Toplam AKTS değerini çıkar (genellikle her yarıyılın sonunda "Toplam AKTS" veya "AKTS" olarak görünür, 1 ile 60 arasında bir sayıdır).
        3. Eksik zorunlu dersleri belirleyip listele (zorunlu dersler aşağıda verilmiştir).
        4. Genel not ortalamasını (Genel Ortalama) çıkar, genellikle 8. yarıyılın sonunda "Genel" kelimesinden sonra görünür.
        5. Her yarıyılın Toplam AKTS değerinin 30 veya daha fazla olup olmadığını kontrol et.
        6. Genel not ortalamasının 2.50 veya daha yüksek olup olmadığını kontrol et.
        7. Öğrencinin mezuniyet şartlarını karşılayıp karşılamadığını belirle (ancak hesaplamaları backend kodunda yapacağız).

        ### Talimatlar:
        - Her yarıyılı (örneğin, "1. Yarıyıl", "2. Yarıyıl" vb.) tanımlayın ve dersleri her yarıyıl altında listeleyin.
        - Her ders için ders kodu (örneğin, "AIB101"), ders adı (örneğin, "Atatürk İlkeleri ve İnkılap Tarihi I") ve not (örneğin, "AA", "BB", "CC", "DD", "FF", "FD", "YT") ekleyin.
        - Her yarıyıl için Toplam AKTS değerini çıkar ve JSON çıktısında her yarıyıl nesnesine "akts" anahtarıyla ekle.
        - Transkript metninde tüm dersleri açıkça listele, hiçbir dersi atlama:
          - Örnek ders formatı: "BM430 Proje Yönetimi 3.0 5.0 BB" -> {{"code": "BM430", "name": "Proje Yönetimi", "grade": "BB"}}
          - 7. ve 8. yarıyıllarda "BM" veya "MTH" önekiyle başlayan tüm dersleri listele (örneğin: "BM424 Derleyici Tasarımı", "BM496 Bilgi Mühendisliği ve Büyük Veriye Giriş").
          - 3. ve 4. yarıyıllarda "US" önekiyle başlayan dersleri listele (örneğin: "US201 Bilim Tarihi ve Felsefesi").
          - 5. ve 6. yarıyıllarda "MS" önekiyle başlayan dersleri listele (örneğin: "MS301 Endüstri İlişkileri").
        - Eksik zorunlu dersleri listele (zorunlu dersler aşağıda verilmiştir).
        - Her yarıyıl için Toplam AKTS değerinin ≥ 30 olup olmadığını kontrol et. Eğer bir yarıyılın AKTS değeri 30'dan düşükse, bunu "akts_issues" listesinde şu formatta belirt: "[Yarıyıl]: Toplam AKTS [değer] < 30".
        - Genel not ortalamasını (Genel Ortalama) çıkar, genellikle 8. yarıyılın sonunda, "Genel" kelimesinden sonra görünür. Not ortalaması bir sayıdır (örneğin, "2.63").
        - Genel not ortalamasının ≥ 2.50 olup olmadığını kontrol et.
        - Transkript metni tutarsız biçimlendirme içerebilir (örneğin، fazla boşluk، eksik satırlar veya özel karakterler). En iyi şekilde ayrıştırmaya çalış:
          - Ders kodları genellikle 5-6 karakter uzunluğundadır (örneğin, "BM430", "US201", "MS301").
          - Ders adları birden fazla kelime olabilir (örneğin, "Proje Yönetimi", "Bilim Tarihi ve Felsefesi").
          - Notlar genellikle "AA", "BB", "CC", "DD", "FF", "FD", "YT" formatındadır.
        - Transkripti ayrıştıramazsanız veya gerekli bilgileri belirleyemezseniz، boş bir JSON nesnesi döndür:
          ```json
          {{}}
          ```
        - Çıktının geçerli JSON formatında olduğundan emin olun (örneğin، dizeler için çift tırnak kullanın، doğru iç içه yapı).
        - "graduation_message" alanını şimdilik boş bırak, bunu backend'de dolduracağız.
        - Sonucu aşağıdaki JSON formatında döndür:

        ```json
        {{
          "semesters": [
            {{
              "semester": "1. Yarıyıl",
              "courses": [
                {{"code": "AIB101", "name": "Atatürk İlkeleri ve İnkılap Tarihi I", "grade": "BB"}},
                {{"code": "BM101", "name": "Algoritmalar ve Programlama I", "grade": "DD"}}
              ],
              "akts": 30
            }},
            ...
          ],
          "gpa": 2.63,
          "missing_mandatory": [
            {{"semester": "1. Yarıyıl", "code": "AIB101", "name": "Atatürk İlkeleri ve İnkılap Tarihi I"}},
            ...
          ],
          "akts_issues": [
            "1. Yarıyıl: Toplam AKTS 25 < 30",
            ...
          ],
          "can_graduate": false,
          "graduation_message": ""
        }}
        ```

        ### Yarıyıl Bazında Gerekli Dersler:
        {json.dumps(MANDATORY_COURSES, ensure_ascii=False, indent=2)}

        ### Yarıyıl Bazında Seçmeli Dersler:
        {json.dumps(ELECTIVE_COURSES, ensure_ascii=False, indent=2)}

        ### Transkript Metni:
        {text}
        """

        # Gemini API'ye istek gönder
        try:
            messages = [
                ("system", "Akademik transkriptleri analiz eden yardımcı bir asistansınız."),
                ("human", prompt)
            ]
            @retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
            def invoke_gemini(messages):
                return llm.invoke(messages)

            ai_msg = invoke_gemini(messages)
            logging.debug(f"Gemini API yanıtı: {ai_msg.content}")

            # Yanıtın boş olup olmadığını kontrol et
            if not ai_msg.content or ai_msg.content.strip() == "":
                return "Gemini API yanıtı boş!", 500

            # Gemini API yanıtını temizle
            response_content = ai_msg.content.strip()
            if response_content.startswith('```json'):
                response_content = response_content[7:]
            if response_content.endswith('```'):
                response_content = response_content[:-3]
            response_content = response_content.strip()

            if not response_content:
                return "Gemini API yanıtı temizlendikten sonra boş!", 500

            # JSON ayrıştırmadan önce yanıtı kontrol et ve düzelt
            try:
                extracted_data = json.loads(response_content)
            except json.JSONDecodeError as e:
                logging.warning(f"JSON ayrıştırma hatası: {str(e)}. Yanıtı düzeltmeyi deniyorum...")
                if response_content.endswith(']') or response_content.endswith('}'):
                    response_content += '}'
                else:
                    response_content += ']}'
                try:
                    extracted_data = json.loads(response_content)
                except json.JSONDecodeError as e:
                    return f"Gemini API yanıtını ayrıştırma hatası (geçerli JSON değil): {str(e)}\nYanıt: {response_content}", 500

            # Manuel olarak dersleri çıkar ve Gemini API yanıtına ekle
            manual_courses = extract_courses_from_text(text)
            extracted_data = merge_extracted_courses(extracted_data, manual_courses)

            # Başarısız zorunlu dersleri kontrol et (yerel olarak)
            failed_mandatory = []
            for semester in extracted_data["semesters"]:
                semester_name = semester["semester"]
                if semester_name in MANDATORY_COURSES:
                    for course in semester["courses"]:
                        mandatory_course = next(
                            (mc for mc in MANDATORY_COURSES[semester_name] if mc["code"] == course["code"]), None)
                        if mandatory_course and course["grade"] in ["FF", "FD"]:
                            failed_mandatory.append({
                                "semester": semester_name,
                                "code": course["code"],
                                "name": course["name"],
                                "grade": course["grade"]
                            })
            extracted_data["failed_mandatory"] = failed_mandatory

            # Zorunlu derslerin eksik olup olmadığını kontrol et
            extracted_data.setdefault("missing_mandatory", [])
            for semester in extracted_data["semesters"]:
                semester_name = semester["semester"]
                if semester_name in MANDATORY_COURSES:
                    for req_course in MANDATORY_COURSES[semester_name]:
                        if not any(course["code"] == req_course["code"] for course in semester["courses"]):
                            extracted_data["missing_mandatory"].append({
                                "semester": semester_name,
                                "code": req_course["code"],
                                "name": req_course["name"]
                            })

            # Başarısız seçmeli dersleri kontrol et (US ve MS)
            failed_electives = []
            failed_elective_codes = set()  # تتبع الدروس الراسبة لمنع التكرار
            for semester in extracted_data["semesters"]:
                semester_name = semester["semester"]
                if semester_name in ELECTIVE_COURSES:
                    for course in semester["courses"]:
                        elective_course = next(
                            (ec for ec in ELECTIVE_COURSES[semester_name] if ec["code"] == course["code"]), None)
                        if elective_course and course["grade"] in ["FF", "FD"] and course["code"] not in failed_elective_codes:
                            failed_electives.append({
                                "semester": semester_name,
                                "code": course["code"],
                                "name": course["name"],
                                "grade": course["grade"]
                            })
                            failed_elective_codes.add(course["code"])
            extracted_data["failed_electives"] = failed_electives

            # AKTS sorunlarını kontrol et
            akts_issues = []
            for semester in extracted_data["semesters"]:
                akts = semester.get("akts", 0)
                if akts < 30:
                    akts_issues.append(f"{semester['semester']}: Toplam AKTS {akts} < 30")
            extracted_data["akts_issues"] = akts_issues

            # 7. ve 8. yarıyıllarda tamamlanan seçmeli ders sayısını hesapla
            completed_electives = count_completed_electives(extracted_data["semesters"])

            # elective_issues'ı güncelle
            required_electives = 10
            extracted_data["elective_issues"] = []  # elective_issues'ı sıfırla
            if completed_electives < required_electives:
                elective_issue = f"7. ve 8. Yarıyıl: Gerekli {required_electives} seçmeli dersten {completed_electives}'ünü tamamladı (BM veya MTH)."
                extracted_data["elective_issues"].append(elective_issue)

            # Başarısız seçmeli dersler için sorunları ekle (US ve MS)
            for failed_elective in failed_electives:
                elective_issue = f"{failed_elective['semester']} döneminde '{failed_elective['name']}' seçmeli dersinden {failed_elective['grade']} ile başarısız oldunuz."
                extracted_data["elective_issues"].append(elective_issue)

            # Mezuniyet durumunu güncelle
            if (completed_electives >= required_electives and
                not extracted_data["missing_mandatory"] and
                not extracted_data["failed_mandatory"] and
                not extracted_data["failed_electives"] and
                not extracted_data["akts_issues"] and
                extracted_data.get("gpa", 0) >= 2.50):
                extracted_data["can_graduate"] = True
                extracted_data["graduation_message"] = "Tebrikler! Öğrenci tüm mezuniyet şartlarını karşıladı."
            else:
                reasons = []
                if extracted_data["missing_mandatory"]:
                    reasons.append("bazı zorunlu derslerin eksikliği")
                if extracted_data["failed_mandatory"]:
                    reasons.append("bazı zorunlu derslerde başarısızlık")
                if extracted_data["failed_electives"]:
                    reasons.append("bazı seçmeli derslerde başarısızlık")
                if completed_electives < required_electives:
                    reasons.append("seçmeli ders sayısında eksiklik")
                if extracted_data["akts_issues"]:
                    reasons.append("bazı yarıyıllarda AKTS eksikliği")
                if extracted_data.get("gpa", 0) < 2.50:
                    reasons.append(f"genel not ortalaması {extracted_data.get('gpa', 0)} (2.50'nin altında)")
                extracted_data["can_graduate"] = False
                extracted_data["graduation_message"] = f"Üzgünüz, öğrenci aşağıdaki nedenlerden dolayı mezun olamadı: {', '.join(reasons)}."

            # Sonuçları sonuç sayfasına geçir (extracted_text kaldırıldı)
            return render_template('result.html', extracted_data=extracted_data)
        except Exception as e:
            if "429" in str(e):
                logging.error(f"Kota aşımı hatası: {str(e)}")
                return "Üzgünüz, Google Gemini API kota limitiniz aşıldı. Lütfen Google AI Studio veya Google Cloud Console'da kota durumunuzu kontrol edin.", 429
            logging.error(f"Gemini API ile iletişim veya veri ayrıştırma hatası: {str(e)}")
            return f"Gemini API ile iletişim veya veri ayrıştırma hatası: {str(e)}", 500

    return "Desteklenmeyen dosya türü! Lütfen yalnızca .docx dosyası yükleyin.", 400

if __name__ == '__main__':
    app.run(debug=True)
