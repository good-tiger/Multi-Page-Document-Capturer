# Multi-Page Document Capturer

![Platform](https://img.shields.io/badge/platform-Windows-blue)
![Python](https://img.shields.io/badge/python-3.9%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

여러 페이지의 문서를 자동으로 캡처해 **PDF / JPEG / PNG** 으로 저장하는 Windows GUI 프로그램.

화면에 표시된 문서(웹 뷰어, 보호된 PDF, 전자책 등)에서 **다음 페이지** 버튼이나 단축키로 페이지를 넘기며 지정한 영역을 반복 캡처하고, 합쳐서 PDF 로 만듭니다.

---

## 요구 사항

- **Windows 10 / 11**
- **Python 3.9 이상**

## 설치

```bash
git clone https://github.com/good-tiger/Multi-Page-Document-Capturer.git
cd Multi-Page-Document-Capturer
pip install -r requirements.txt
```

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
     - 캡처한 이미지를 LANCZOS 보간으로 업스케일링하여 PDF 의 실효 해상도를 키웁니다.
   - JPEG / PNG 폴더 저장 (체크박스)
6. ▶ **실행**
   - 3초 카운트다운 동안 캡처 대상 창(브라우저, PDF 뷰어 등)을 활성화
   - 캡처 완료 → PDF 저장 → 옵션 폴더 저장 순으로 진행

> **선택 결과 시각화**: 캡처 영역을 고르면 빨간 사각형이, 클릭 좌표를 고르면 녹색 표적이 화면 위에 항상 표시됩니다. 오버레이는 클릭이 통과되어 다른 창 사용을 방해하지 않으며, ▶ 실행 중에는 캡처 결과에 찍히지 않도록 자동으로 숨겨집니다.

## 결과물 구조

저장 위치 `D:\docs`, 파일명 `report` 인 경우, **파일명과 동일한 폴더가 생성**되고 그 안에 PDF 와 이미지 폴더가 모두 들어갑니다.

```
D:\docs\
└── report\                   ← 파일명으로 만든 폴더
    ├── report.pdf            ← 항상 생성 (선택 DPI 적용)
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

## 라이선스

이 프로젝트는 [MIT License](LICENSE) 하에 배포됩니다.
