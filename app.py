from flask import Flask, render_template, request
import os
import docx2txt
from langchain_google_genai import ChatGoogleGenerativeAI
import json
import re
import logging


app = Flask(__name__)

# Kurulum için günlük kaydı
logging.basicConfig(level=logging.DEBUG)

# Yüklenen dosyalar için klasör
UPLOAD_FOLDER = 'backend/uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Google AI API anahtarı
from dotenv import load_dotenv
import os

load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")  # Kendi API anahtarınızla değiştirin

# Gemini API istemcisini kur
llm = ChatGoogleGenerativeAI(
    model="gemini-1.5-flash",
    google_api_key=GOOGLE_API_KEY,
    temperature=0,
    max_tokens=2000
)

# Çıkarılan metni temizleme fonksiyonu
def clean_text(text):
    text = re.sub(r'\s+', ' ', text.strip())
    text = re.sub(r'[^\w\s\d\.\:\*\-]', '', text)
    return text

# 7. ve 8. yarıyıllarda tamamlanan seçmeli ders sayısını hesaplama
def count_completed_electives(semesters):
    elective_courses = []
    for semester in semesters:
        if semester["semester"] in ["7. Yarıyıl", "8. Yarıyıl"]:
            for course in semester["courses"]:
                if course["code"] in ["BM401", "BM499", "BM498"]:
                    continue
                if course["code"].startswith("BM") or course["code"].startswith("MTH"):
                    if course["grade"] not in ["FF", "FD"]:
                        elective_courses.append(course)
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
        3. Çıkarılan dersleri her yarıyıl için zorunlu ve seçmeli derslerle karşılaştır (aşağıda verilmiştir).
        4. Eksik zorunlu veya seçmeli dersleri belirleyip listele.
        5. Genel not ortalamasını (Genel Ortalama) çıkar, genellikle 8. yarıyılın sonunda "Genel" kelimesinden sonra görünür.
        6. Her yarıyılın Toplam AKTS değerinin 30 veya daha fazla olup olmadığını kontrol et.
        7. Genel not ortalamasının 2.50 veya daha yüksek olup olmadığını kontrol et.
        8. Öğrencinin mezuniyet şartlarını karşılayıp karşılamadığını belirle:
           - Tüm zorunlu dersler mevcut ve geçilmiş olmalı (FF veya FD dışında not, stajlar için YT).
           - Tüm seçmeli ders gereksinimleri karşılanmış olmalı (her yarıyıl için doğru sayıda seçmeli ders).
           - Her yarıyılın Toplam AKTS değeri ≥ 30 olmalı (30'dan fazla olabilir).
           - Genel not ortalaması ≥ 2.50 olmalı.
        9. Sonuçları yapılandırılmış JSON formatında döndür, öğrencinin mezun olup olmadığını belirten bir mesajla.

        ### Talimatlar:
        - Her yarıyılı (örneğin, "1. Yarıyıl", "2. Yarıyıl" vb.) tanımlayın ve dersleri her yarıyıl altında listeleyin.
        - Her ders için ders kodu (örneğin, "AIB101"), ders adı (örneğin, "Atatürk İlkeleri ve İnkılap Tarihi I") ve not (örneğin, "AA", "BB", "CC", "DD", "FF", "FD", "YT") ekleyin.
        - Her yarıyıl için Toplam AKTS değerini çıkar ve JSON çıktısında her yarıyıl nesnesine "akts" anahtarıyla ekle.
        - Bir dersin notu "YT" (Yeterli) ise, öğrenci bu dersi geçmiş demektir (genellikle stajlar için).
        - Bir dersin geçilip geçilmediği şu şekilde belirlenir:
          - Not "FF" veya "FD" değilse.
          - Not "YT" ise (stajlar için).
          - Not "FF" veya "FD" ise, ders başarısızdır.
        - Çıkarılan dersleri her yarıyıl için gerekli derslerle (zorunlu ve seçmeli) karşılaştır:
          - Eksik zorunlu dersleri listele.
          - Notu "FF" veya "FD" olan zorunlu dersleri başarısız zorunlu dersler olarak listele (bunlar mezuniyeti engeller).
          - 1-6. yarıyıllardaki seçmeli dersler için öğrencinin doğru önekle (örneğin, "US", "MS") gerekli sayıda dersi alıp almadığını kontrol et.
          - 7. ve 8. yarıyıllardaki seçmeli dersler için:
            - Seçmeli dersler "BM" veya "MTH" önekiyle başlar.
            - Öğrenci 7. ve 8. yarıyıllarda toplam 10 seçmeli ders tamamlamalıdır.
            - "BM401", "BM499" ve "BM498" kodlu dersler zorunludur ve seçmeli olarak sayılmaz.
            - Notu "FF" veya "FD" olan seçmeli dersler (BM veya MTH önekli) başarısız sayılmaz, sadece gerekli 10 seçmeli ders için sayılmaz.
        - Her yarıyıl için Toplam AKTS değerinin ≥ 30 olup olmadığını kontrol et. Eğer bir yarıyılın AKTS değeri 30'dan düşükse, bunu "akts_issues" listesinde şu formatta belirt: "[Yarıyıl]: Toplam AKTS [değer] < 30".
        - Genel not ortalamasını (Genel Ortalama) çıkar, genellikle 8. yarıyılın sonunda, "Genel" kelimesinden sonra görünür. Not ortalaması bir sayıdır (örneğin, "2.63").
        - Genel not ortalamasının ≥ 2.50 olup olmadığını kontrol et.
        - Öğrencinin mezun olup olamayacağını belirle:
          - Öğrenci mezun olabilir eğer:
            - Tüm zorunlu dersler mevcut ve geçilmiş.
            - Tüm seçmeli ders gereksinimleri karşılanmış (7. ve 8. yarıyıllarda 10 seçmeli ders dahil).
            - Her yarıyılın Toplam AKTS değeri ≥ 30.
            - Genel not ortalaması ≥ 2.50.
          - Aksi takdirde, öğrenci mezun olamaz.
        - Transkript metni tutarsız biçimlendirme içerebilir (örneğin, fazla boşluk, eksik satırlar veya özel karakterler). En iyi şekilde ayrıştırmaya çalış.
        - Transkripti ayrıştıramazsanız veya gerekli bilgileri belirleyemezseniz, boş bir JSON nesnesi döndür:
          ```json
          {{}}
          ```
        - Çıktının geçerli JSON formatında olduğundan emin olun (örneğin, dizeler için çift tırnak kullanın, doğru iç içe yapı).
        - "graduation_message" alanının Türkçe olduğundan emin olun, şu formatta: "Üzgünüz, öğrenci bazı zorunlu derslerde başarısız olduğu için mezun olamadı." veya "Tebrikler! Öğrenci tüm mezuniyet şartlarını karşıladı."
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
          "elective_issues": [
            "7. ve 8. Yarıyıl: Gerekli 10 seçmeli dersten 3'ünü tamamladı (BM veya MTH).",
            ...
          ],
          "akts_issues": [
            "1. Yarıyıl: Toplam AKTS 25 < 30",
            ...
          ],
          "failed_mandatory": [
            {{"semester": "6. Yarıyıl", "code": "BM302", "name": "Bilgisayar Ağları II", "grade": "FF"}},
            ...
          ],
          "can_graduate": false,
          "graduation_message": "Üzgünüz, öğrenci bazı zorunlu derslerde başarısız olduğu için mezun olamadı."
        }}
        ```

        ### Yarıyıl Bazında Gerekli Dersler:
        {json.dumps(MANDATORY_COURSES, ensure_ascii=False, indent=2)}

        ### 7. ve 8. Yarıyıl için Seçmeli Dersler (BM veya MTH önekli):
        - BM429: Optimizasyon
        - BM433: Sayısal İşaret İşleme
        - BM447: Sayısal Görüntü İşleme
        - BM480: Derin Öğrenme
        - BM455: Bulanık Mantığa Giriş
        - BM437: Yapay Zeka
        - BM489: Programlanabilir Mantık Denetleyiciler
        - BM441: Bilgisayar Güvenliğine Giriş
        - BM449: Ağ Güvenliğine Giriş
        - BM472: Ağ Programlama
        - BM481: Sanallaştırma Teknolojileri
        - BM478: Python İle Veri Bilimine Giriş
        - BM471: Gömülü Sistem Uygulamaları
        - BM482: Yazılım Gereksinimleri Mühendisliği
        - BM485: Dosya Organizasyonu
        - BM486: Sayısal Sistem Tasarım
        - BM487: Nesnelerin İnterneti
        - BM488: Veri Analizi ve Tahminleme Yöntemleri
        - BM490: Bilgi Güvenliği
        - BM491: Sistem Biyolojisi
        - BM492: Tıbbi İstatistik ve Tıp Bilimine Giriş
        - BM493: Veri İletişimi
        - BM494: Kablosuz Haberleşme
        - BM495: İleri Gömülü Sistem Uygulamaları
        - BM422: Biyobilişime Giriş
        - BM438: Yurtdışı Staj Etkinliği
        - BM428: Oyun Programlamaya Giriş
        - BM459: Yazılım Test Mühendisliği
        - BM475: Kurumsal Java
        - BM479: Kompleks Ağ Analizi
        - BM423: Bulanık Mantık ve Yapay Sinir Ağlarına Giriş
        - BM435: Veri Madenciliği
        - BM463: İleri Sistem Programlama
        - BM440: Veri Tabanı Tasarımı ve Uygulamaları
        - BM457: Bilgisayar Aritmetiği ve Otomata
        - BM442: Görsel Programlama
        - BM430: Proje Yönetimi
        - BM469: Makine Öğrenmesine Giriş
        - BM424: Derleyici Tasarımı
        - BM451: Kontrol Sistemlerine Giriş
        - BM432: Robotik
        - BM434: Sayısal Kontrol Sistemleri
        - BM465: Mikrodenetleyiciler ve Uygulamaları
        - BM420: Bilgisayar Mimarileri
        - BM431: Örüntü Tanıma
        - BM426: Gerçek Zamanlı Ağ Sistemleri
        - BM436: Sistem Simülasyonu
        - BM461: Coğrafi Bilgi Sistemleri
        - BM474: ERP Uygulamaları
        - BM427: İnternet Mühendisliği
        - BM453: İçerik Yönetim Sistemleri
        - BM439: Bilgisayar Görmesi
        - BM425: Erp Sistemleri
        - BM473: Karar Destek Sistemleri
        - BM443: Mobil Programlama
        - BM445: Java Programlama
        - BM470: İleri Java Programlama
        - BM496: Bilgi Mühendisliği ve Büyük Veriye Giriş
        - BM421: Bilgisayar Grafiği
        - BM477: Graf Teorisi
        - BM444: Yazılım Tasarım Kalıpları
        - BM467: Kodlama Teorisi ve Kriptografi
        - BM476: Açık Kaynak Programlama

        ### Transkript Metni:
        {text}
        """

        # Gemini API'ye istek gönder
        try:
            messages = [
                ("system", "Akademik transkriptleri analiz eden yardımcı bir asistansınız."),
                ("human", prompt)
            ]
            ai_msg = llm.invoke(messages)
            logging.debug(f"Gemini API yanıtı: {ai_msg.content}")

            # Yanıtın boş olup olmadığını kontrol et
            if not ai_msg.content or ai_msg.content.strip() == "":
                return "Gemini API yanıtı boş!", 500

            # Gemini API yanıtını temizله
            response_content = ai_msg.content.strip()
            if response_content.startswith('```json'):
                response_content = response_content[7:]
            if response_content.endswith('```'):
                response_content = response_content[:-3]
            response_content = response_content.strip()

            if not response_content:
                return "Gemini API yanıtı temizlendikten sonra boş!", 500

            # Yanıtı JSON'a dönüştürmه
            extracted_data = json.loads(response_content)

            # Zorunlu derslerin eksik olup olmadığını kontrol et
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
            if completed_electives < required_electives:
                elective_issue = f"7. ve 8. Yarıyıl: Gerekli {required_electives} seçmeli dersten {completed_electives}'ünü tamamladı (BM veya MTH)."
                extracted_data["elective_issues"] = [issue for issue in extracted_data["elective_issues"] if
                                                    not issue.startswith("7. ve 8. Yarıyıl:")]
                extracted_data["elective_issues"].append(elective_issue)

            # Mezuniyet durumunu güncelle
            if (completed_electives >= required_electives and
                not extracted_data["missing_mandatory"] and
                not extracted_data["failed_mandatory"] and
                not extracted_data["akts_issues"] and
                extracted_data["gpa"] >= 2.50):
                extracted_data["can_graduate"] = True
                extracted_data["graduation_message"] = "Tebrikler! Öğrenci tüm mezuniyet şartlarını karşıladı."
            else:
                reasons = []
                if extracted_data["missing_mandatory"]:
                    reasons.append("bazı zorunlu derslerin eksikliği")
                if extracted_data["failed_mandatory"]:
                    reasons.append("bazı zorunlu derslerde başarısızlık")
                if completed_electives < required_electives:
                    reasons.append("seçmeli ders sayısında eksiklik")
                if extracted_data["akts_issues"]:
                    reasons.append("bazı yarıyıllarda AKTS eksikliği")
                if extracted_data["gpa"] < 2.50:
                    reasons.append("genel not ortalaması 2.50'nin altında")
                extracted_data["can_graduate"] = False
                extracted_data["graduation_message"] = f"Üzgünüz, öğrenci {', '.join(reasons)} nedeniyle mezun olamadı."

            # Sonuçları sonuç sayfasına geçir
            return render_template('result.html', extracted_data=extracted_data)
        except json.JSONDecodeError as e:
            return f"Gemini API yanıtını ayrıştırma hatası (geçerli JSON değil): {str(e)}\nYanıt: {response_content}", 500
        except Exception as e:
            return f"Gemini API ile iletişim veya veri ayrıştırma hatası: {str(e)}", 500

    return "Desteklenmeyen dosya türü! Lütfen yalnızca .docx dosyası yükleyin.", 400

if __name__ == '__main__':
    app.run(debug=True)