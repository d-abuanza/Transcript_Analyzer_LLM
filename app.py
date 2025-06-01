from flask import Flask, render_template, request
import os
import docx2txt
from langchain_google_genai import ChatGoogleGenerativeAI
import json
import re
import logging
from tenacity import retry, stop_after_attempt, wait_fixed
from dotenv import load_dotenv

app = Flask(__name__)
logging.info("Flask uygulaması başarıyla başlatıldı")

# Günlük kaydı için ayar
logging.basicConfig(level=logging.DEBUG, filename='app.log', format='%(asctime)s - %(levelname)s - %(message)s')

# Yüklenen dosyalar için klasör
UPLOAD_FOLDER = 'backend/uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Google AI API anahtarını yükle
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
    text = re.sub(r'[^\w\s\d\.\:\*\-\(\)]', '', text)  # Parantezleri koru
    return text

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

# Seçmeli derslerin listesi
ELECTIVE_COURSES = {
    "3. Yarıyıl": [
        {"code": "US201", "name": "Bilim Tarihi ve Felsefesi"},
        {"code": "US207", "name": "Girişimcilik"},
        {"code": "US211", "name": "İş Psikolojisi"},
        {"code": "US213", "name": "İşletme Yönetimi"},
        {"code": "US215", "name": "Kültür Tarihi"},
        {"code": "US217", "name": "Sanat Tarihi"},
        {"code": "US219", "name": "Sivil Toplum Organizasyonu"},
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
        {"code": "US219", "name": "Sivil Toplum Organizasyonu"},
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
        try:
            file.save(file_path)
        except Exception as e:
            logging.error(f"Dosya kaydetme hatası: {str(e)}")
            return f"Dosya kaydetme hatası: {str(e)}", 500

        # .docx dosyasından metni çıkar
        try:
            text = docx2txt.process(file_path)
            text = clean_text(text)
            logging.debug(f"Çıkarılmış metin: {text[:500]}...")  # İlk 500 karakteri günlüğe kaydet
        except Exception as e:
            logging.error(f"Metin çıkarma hatası: {str(e)}")
            return f"Metin çıkarma hatası: {str(e)}", 500

        # Gemini API için prompt hazırlığı
        prompt = f"""
        Akademik transkriptleri analiz eden yardımcı bir asistansınız. Aşağıdaki transkript metnine göre aşağıdaki adımları gerçekleştirin:

        ### Görev:
        1. Transkriptten tüm dersleri ve notlarını yarıyıl bazında çıkar.
        2. Her yarıyıl için Toplam AKTS değerini çıkar (genellikle her yarıyılın sonunda "Toplam AKTS" veya "AKTS" olarak görünür, 1 ile 60 arasında bir sayıdır).
        3. Genel not ortalamasını (Genel Ortalama) çıkar, **son yarıyılın** sonunda "Genel" kelimesinden sonra görünür (örneğin, transkript 7 yarıyıl içeriyorsa 7. yarıyılın sonunda, 6 yarıyıl içeriyorsa 6. yarıyılın sonunda). Not ortalaması bir sayıdır (örneğin, "2.63").

        ### Talimatlar:
        - Her yarıyılı (örneğin, "1. Yarıyıl", "2. Yarıyıl" vb.) tanımlayın ve dersleri her yarıyıl altında listeleyin.
        - Her ders için ders kodu (örneğin, "AIB101"), ders adı (örneğin, "Atatürk İlkeleri ve İnkılap Tarihi I") ve not (örneğin, "AA", "BB", "CC", "DD", "FF", "FD", "YT") ekleyin.
        - Her yarıyıl için Toplam AKTS değerini çıkar ve JSON çıktısında her yarıyıl nesnesine "akts" anahtarıyla ekle.
        - Transkript metninde tüm dersleri açıkça listele, hiçbir dersi atlama:
          - Örnek ders formatı: "BM430 Proje Yönetimi 3.0 5.0 BB" -> {{"code": "BM430", "name": "Proje Yönetimi", "grade": "BB"}}
          - Alternatif format: "BM211 - Diferansiyel Denklemler (Yarıyıl: 3. Yarıyıl)" -> {{"code": "BM211", "name": "Diferansiyel Denklemler", "grade": "BB"}} (Not belirtilmemişse varsayılan olarak "BB" kullan).
        - Transkript metni tutarsız biçimlendirme içerebilir (örneğin, fazla boşluk, eksik satırlar veya özel karakterler). En iyi şekilde ayrıştırmaya çalış:
          - Ders kodları genellikle 5-6 karakter uzunluğundadır (örneğin, "BM430", "US201", "MS301").
          - Ders adları birden fazla kelime olabilir (örneğin, "Proje Yönetimi", "Bilim Tarihi ve Felsefesi").
          - Notlar genellikle "AA", "BB", "CC", "DD", "FF", "FD", "YT" formatındadır.
        - Transkripti ayrıştıramazsanız veya gerekli bilgileri belirleyemezseniz, boş bir JSON nesnesi döndür:
          ```json
          {{}}
          ```
        - Çıktının geçerli JSON formatında olduğundan emin olun (örneğin, dizeler için çift tırnak kullanın, doğru iç içe yapı).
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
          "gpa": 2.63
        }}

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
            logging.debug(f"Gemini API yanıtı: {ai_msg.content[:500]}...")  # İlk 500 karakteri günlüğe kaydet

            # Yanıtın boş olup olmadığını kontrol et
            if not ai_msg.content or ai_msg.content.strip() == "":
                logging.error("Gemini API yanıtı boş!")
                return "Gemini API yanıtı boş!", 500

            # Gemini API yanıtını temizle
            response_content = ai_msg.content.strip()
            if response_content.startswith('```json'):
                response_content = response_content[7:]
            if response_content.endswith('```'):
                response_content = response_content[:-3]
            response_content = response_content.strip()

            if not response_content:
                logging.error("Gemini API yanıtı temizlendikten sonra boş!")
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
                    logging.error(f"Gemini API yanıtını ayrıştırma hatası: {str(e)}\nYanıt: {response_content}")
                    return f"Gemini API yanıtını ayrıştırma hatası (geçerli JSON değil): {str(e)}", 500

            # extracted_data'nın temel yapısını kontrol et ve eksik anahtarları ekle
            if not isinstance(extracted_data, dict):
                extracted_data = {}
            extracted_data.setdefault("semesters", [])
            extracted_data.setdefault("gpa", 0.0)

            # Mevcut yarıyılları kontrol et ve eksik yarıyılları bul
            available_semesters = [sem["semester"] for sem in extracted_data["semesters"]]
            last_semester = 0
            if available_semesters:
                last_semester = max([int(sem.split('.')[0]) for sem in available_semesters])
            else:
                logging.debug("Hiçbir yarıyıl bulunamadı, last_semester 0 olarak ayarlandı.")

            expected_semesters = [f"{i}. Yarıyıl" for i in range(1, 9)]
            missing_semesters = [sem for sem in expected_semesters if sem not in available_semesters]
            extracted_data["missing_semesters"] = missing_semesters  # Eksik yarıyılları ekle
            logging.debug(f"Eksik yarıyıllar: {missing_semesters}")

            # Başarısız zorunlu dersleri kontrol et
            failed_mandatory = []
            for semester in extracted_data["semesters"]:
                semester_name = semester["semester"]
                if semester_name in MANDATORY_COURSES:
                    for course in semester["courses"]:
                        mandatory_course = next(
                            (mc for mc in MANDATORY_COURSES[semester_name] if
                             mc["code"].strip() == course["code"].strip()), None)
                        if mandatory_course and course["grade"] in ["FF", "FD"]:
                            failed_mandatory.append({
                                "semester": semester_name,
                                "code": course["code"],
                                "name": course["name"],
                                "grade": course["grade"]
                            })
            extracted_data["failed_mandatory"] = failed_mandatory

            # Zorunlu derslerin eksik olup olmadığını kontrol et
            missing_mandatory_codes = set()
            missing_mandatory = []
            for semester in extracted_data["semesters"]:
                semester_name = semester["semester"]
                if semester_name in MANDATORY_COURSES:
                    semester_course_codes = {course["code"].strip() for course in semester["courses"]}
                    logging.debug(f"{semester_name} için mevcut ders kodları: {semester_course_codes}")
                    for req_course in MANDATORY_COURSES[semester_name]:
                        if req_course["code"].strip() not in semester_course_codes:
                            if req_course["code"] not in missing_mandatory_codes:
                                missing_mandatory.append({
                                    "semester": semester_name,
                                    "code": req_course["code"],
                                    "name": req_course["name"]
                                })
                                missing_mandatory_codes.add(req_course["code"])
                                logging.debug(f"Eksik zorunlu ders eklendi: {semester_name} - {req_course['code']}")

            # Eksik yarıyıllardaki zorunlu dersleri ekle
            for missing_sem in missing_semesters:
                if missing_sem in MANDATORY_COURSES:
                    for req_course in MANDATORY_COURSES[missing_sem]:
                        if req_course["code"] not in missing_mandatory_codes:
                            missing_mandatory.append({
                                "semester": missing_sem,
                                "code": req_course["code"],
                                "name": req_course["name"]
                            })
                            missing_mandatory_codes.add(req_course["code"])
                            logging.debug(f"Eksik yarıyıl zorunlu dersi eklendi: {missing_sem} - {req_course['code']}")
            extracted_data["missing_mandatory"] = missing_mandatory

            # Başarısız seçmeli dersleri kontrol et (US ve MS)
            failed_electives = []
            failed_elective_codes = set()
            for semester in extracted_data["semesters"]:
                semester_name = semester["semester"]
                if semester_name in ELECTIVE_COURSES:
                    for course in semester["courses"]:
                        elective_course = next(
                            (ec for ec in ELECTIVE_COURSES[semester_name] if
                             ec["code"].strip() == course["code"].strip()), None)
                        if elective_course and course["grade"] in ["FF", "FD"] and course[
                            "code"] not in failed_elective_codes:
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
                if akts is None:
                    akts = 0
                if akts < 30:
                    akts_issues.append(f"{semester['semester']}: Toplam AKTS {akts} < 30")
            for missing_sem in missing_semesters:
                akts_issues.append(f"{missing_sem}: Toplam AKTS 0 < 30 (Yarıyıl eksik)")
            extracted_data["akts_issues"] = akts_issues

            # Seçmeli ders sayısını kontrol et
            elective_issues = []

            # 3. ve 4. yarıyıllarda US dersleri (1 US dersi gerekli)
            for sem_num in [3, 4]:
                sem_key = f"{sem_num}. Yarıyıl"
                if sem_key in available_semesters:
                    us_courses = [c for c in extracted_data["semesters"][available_semesters.index(sem_key)]["courses"]
                                  if c["code"].startswith("US") and c["grade"] not in ["FF", "FD"]]
                    if len(us_courses) < 1:
                        elective_issues.append(f"{sem_num}. Yarıyıl'da US kodlu bir ders eksik.")
                elif sem_key in ELECTIVE_COURSES:
                    elective_issues.append(f"{sem_num}. Yarıyıl'da US kodlu bir ders eksik.")

            # 5. ve 6. yarıyıllarda MS dersleri (1 MS dersi gerekli)
            for sem_num in [5, 6]:
                sem_key = f"{sem_num}. Yarıyıl"
                if sem_key in available_semesters:
                    ms_courses = [c for c in extracted_data["semesters"][available_semesters.index(sem_key)]["courses"]
                                  if c["code"].startswith("MS") and c["grade"] not in ["FF", "FD"]]
                    if len(ms_courses) < 1:
                        elective_issues.append(f"{sem_num}. Yarıyıl'da MS kodlu bir ders eksik.")
                elif sem_key in ELECTIVE_COURSES:
                    elective_issues.append(f"{sem_num}. Yarıyıl'da MS kodlu bir ders eksik.")

            # 7. ve 8. yarıyıllarda BM/MTH dersleri (10 ders gerekli)
            bm_mth_courses = []
            for sem_num in [7, 8]:
                sem_key = f"{sem_num}. Yarıyıl"
                if sem_key in available_semesters:
                    bm_mth_courses += [c for c in extracted_data["semesters"][available_semesters.index(sem_key)]["courses"]
                                       if (c["code"].startswith("BM") or c["code"].startswith("MTH"))
                                       and c["code"] not in ["BM401", "BM499", "BM498"]
                                       and c["grade"] not in ["FF", "FD"]]
            if last_semester >= 7 and len(bm_mth_courses) < 10:
                elective_issues.append(f"7. ve 8. Yarıyıl'da en az 10 BM/MTH dersi alınmalı (Alınan: {len(bm_mth_courses)})")

            extracted_data["elective_issues"] = elective_issues

            # Mezuniyet durumunu güncelle
            gpa = extracted_data.get("gpa", 0)
            if gpa is None:
                gpa = 0.0
                logging.debug("GPA None olarak geçti, 0.0 olarak ayarlandı.")

            graduation_reasons = []

            # Eksik yarıyıl kontrolü
            if last_semester < 8:
                graduation_reasons.append(f"Eksik yarıyıl sayısı: {8 - last_semester} ({', '.join(missing_semesters)})")

            # Zorunlu ders kontrolü
            if missing_mandatory:
                graduation_reasons.append(f"Eksik zorunlu ders sayısı: {len(missing_mandatory)}")

            # Başarısız zorunlu ders kontrolü
            if failed_mandatory:
                graduation_reasons.append(f"Başarısız zorunlu ders sayısı: {len(failed_mandatory)}")

            # Başarısız seçmeli ders kontrolü
            if failed_electives:
                graduation_reasons.append(f"Başarısız seçmeli ders sayısı: {len(failed_electives)}")

            # AKTS kontrolü
            if akts_issues:
                graduation_reasons.append(f"AKTS eksikliği olan yarıyıl sayısı: {len(akts_issues)}")

            # Seçmeli ders kontrolü
            if elective_issues:
                graduation_reasons.append(f"Seçmeli ders eksiklikleri: {len(elective_issues)}")

            # GPA kontrolü
            if gpa < 2.50:
                graduation_reasons.append(f"Genel not ortalaması yetersiz: {gpa:.2f} (Gereken: 2.50)")

            # Mezuniyet durumunu belirle
            if (last_semester >= 8 and
                    not missing_mandatory and
                    not failed_mandatory and
                    not failed_electives and
                    not akts_issues and
                    not elective_issues and
                    gpa >= 2.50):
                extracted_data["can_graduate"] = True
                extracted_data["graduation_message"] = "Tebrikler! Tüm mezuniyet şartlarını karşılıyorsunuz."
            else:
                extracted_data["can_graduate"] = False
                extracted_data["graduation_message"] = f"Mezuniyet şartları karşılanmadı:\n- " + "\n- ".join(graduation_reasons)

            # Sonuçları sonuç sayfasına geçir
            return render_template('result.html', extracted_data=extracted_data)
        except Exception as e:
            if "429" in str(e):
                logging.error(f"Kota aşımı hatası: {str(e)}")
                return "Üzgünüz, Google Gemini API kota sınırınızı aştınız. Google AI Studio veya Google Cloud Console'da kota durumunuzu kontrol edin.", 429
            logging.error(f"Gemini API ile iletişim veya veri ayrıştırma hatası: {str(e)}")
            return f"İstek işlenirken hata oluştu: {str(e)}", 500

    return "Desteklenmeyen dosya formatı! Lütfen yalnızca .docx dosyası yükleyin.", 400

if __name__ == '__main__':
    app.run(debug=True)
