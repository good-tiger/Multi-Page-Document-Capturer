# Multi-Page Document Capturer

![Platform](https://img.shields.io/badge/platform-Windows-blue)
![Python](https://img.shields.io/badge/python-3.9%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

여러 페이지의 문서를 자동으로 캡처해 **PDF / 이미지 / 마크다운(OCR)** 으로 저장하는 Windows GUI 프로그램.

화면에 표시된 문서(웹 뷰어, 보호된 PDF, 전자책 등)에서 **다음 페이지** 버튼이나 단축키로 페이지를 넘기며 지정한 영역을 반복 캡처하고, 합쳐서 PDF 로 만든 뒤 OCR 로 마크다운까지 추출합니다.

---

## 요구 사항

- **Windows 10 / 11**
- **Python 3.9 이상**
- **Java 11 이상** (PATH 등록 필요) — OpenDataLoader 의 hybrid OCR 백엔드 실행에 사용
  - https://adoptium.net 에서 설치

## 설치

```bash
git clone https://github.com/<your-username>/Multi-Page-Document-Capturer.git
cd Multi-Page-Document-Capturer
pip install -r requirements.txt
```

> `opendataloader-pdf[hybrid]` 는 docling 등 무거운 의존성을 함께 설치합니다. 첫 설치 시 시간이 다소 걸릴 수 있습니다.

## 실행

```bash
python page_capture.py
```

---

## 사용 흐름

1. **캡처 영역**: "영역 선택" 버튼 → 화면이 어두워지면 마우스로 영역을 드래그
2. **다음 페이지 이동 방식**:
   - **좌표 클릭**: "좌표 선택" → 다음 페이지 버튼 위치를 클릭
   - **단축키**: `right`, `pagedown`, `space`, `ctrl+right` 등
3. **페이지 수** / **페이지 간 대기 시간(초)**
4. **저장 위치 / 파일명**
5. **추가 출력 옵션**
   - **PDF 화질** (라디오): 100 / 200 / 300 DPI
     - 높을수록 OCR 정확도 ↑, 파일 크기 ↑
     - 캡처한 이미지를 LANCZOS 보간으로 업스케일링하여 PDF 의 실효 해상도를 키웁니다.
   - JPEG / PNG 폴더 저장 (체크박스)
   - 마크다운 변환 (체크박스) — OpenDataLoader **hybrid 모드**로 OCR 수행
   - **OCR 언어**: `ko,en`(기본), `ja`, `ch_sim`, `en` 등 콤마 구분
6. ▶ **실행**
   - 3초 카운트다운 동안 캡처 대상 창(브라우저, PDF 뷰어 등)을 활성화
   - 캡처 완료 → PDF 저장 → 옵션 폴더 저장 → 마크다운 변환 순으로 진행

## 마크다운 변환의 동작

이미지로만 구성된 PDF(예: 화면 캡처)는 텍스트 레이어가 없어서 일반 PDF 파서로는 이미지 링크만 추출됩니다. 이 프로그램은 OpenDataLoader 의 **hybrid 모드 + OCR** 을 자동으로 동작시킵니다.

내부 흐름:

1. `opendataloader-pdf-hybrid` 백엔드를 서브프로세스로 실행 (`--port 5002 --force-ocr --ocr-lang ko,en`)
2. 백엔드가 응답할 때까지 폴링 (최대 60초)
3. Python API 로 변환 호출 (`hybrid="docling-fast"`)
4. 변환 완료 후 백엔드 종료, `.md` 파일을 지정한 위치로 이동

> 첫 실행 시 docling 모델/리소스를 다운로드하므로 수 분이 걸릴 수 있습니다.

## 결과물 구조

저장 위치 `D:\docs`, 파일명 `report` 인 경우:

```
D:\docs\
├── report.pdf            ← 항상 생성 (선택 DPI 적용)
├── report.md             ← OCR 마크다운 옵션 ON 시
├── jpeg\                 ← JPEG 옵션 ON 시
│   ├── report_001.jpg
│   └── ...
└── png\                  ← PNG 옵션 ON 시
    ├── report_001.png
    └── ...
```

## 단축키 입력 형식 예시

| 표기                          | 의미                      |
| ----------------------------- | ------------------------- |
| `right`, `left`, `up`, `down` | 방향키                    |
| `pagedown`, `pageup`          | Page Down/Up              |
| `space`                       | 스페이스바                |
| `enter`                       | 엔터                      |
| `ctrl+right`                  | 동시 입력 (Ctrl + 오른쪽) |

---

## 알려진 제한 / 트러블슈팅

- **pyautogui 안전장치**: 마우스를 화면 좌상단 모서리로 옮기면 자동화가 즉시 중단됩니다.
- **포커스**: 단축키 방식은 캡처 대상 창이 활성 상태여야 합니다. 시작 카운트다운(3초) 동안 대상 창을 클릭해 활성화하세요.
- **DPI 스케일링**: Windows 디스플레이 배율이 100% 가 아니면 좌표가 어긋날 수 있습니다. 배율을 100% 로 맞춘 뒤 사용하세요.
- **멀티 모니터**: 주 모니터 외 영역에서는 좌표가 틀어질 수 있습니다.
- **Java 미설치 오류**: 마크다운 변환 시 백엔드 실행 실패 → `java -version` 으로 PATH 확인.
- **OCR 정확도**: 200 DPI 이상을 권장합니다. 100 DPI 는 글자가 작은 문서에서 인식률이 떨어질 수 있습니다.
- **첫 실행 속도**: hybrid 의존성과 모델 다운로드가 있어 처음 한 번만 매우 느립니다.

## 라이선스

이 프로젝트는 [MIT License](LICENSE) 하에 배포됩니다.
