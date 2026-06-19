# Bộ công cụ DXF → RAM Concept

Một ứng dụng Windows duy nhất gộp **hai công cụ** để đưa dữ liệu kết cấu từ bản
vẽ DXF vào **RAM Concept 2023**:

| Công cụ | Chức năng |
|---------|-----------|
| **Mesh Model Builder** | Đọc bản vẽ DXF, gán layer cho từng cấu kiện (sàn / cột / vách / lỗ mở) và tự động sinh model RAM Concept đã chia mesh (`.cpt`). |
| **Area Load Importer** | Đọc bản vẽ tải DXF, canh khớp lên sàn RAM Concept đã có, rồi click từng vùng để gán tải **SDL** và **LL** và import vào model. |

Khi mở app sẽ hiện **màn hình chọn (launcher)** — bấm vào thẻ tương ứng để mở
công cụ cần dùng. Mỗi công cụ mở trong cửa sổ riêng nên có thể chạy cả hai cùng lúc.

---

## 1. Yêu cầu

- **Windows 10/11 (64-bit).**
- Đã cài **RAM Concept 2023** ở thư mục mặc định
  `C:\Program Files\Bentley\Engineering\RAM Concept\RAM Concept 2023\python`.
  Đây là bắt buộc để thực sự **tạo / import** vào model (app giao tiếp với RAM
  Concept qua Python API của nó).
- **Không cần cài Python** — mọi thứ (kể cả thư viện `ezdxf`) đã được đóng gói
  sẵn trong file `.exe`.

> Nếu chưa cài RAM Concept, bạn vẫn mở được file DXF và bố trí công việc, nhưng
> bước "Run / Import" cuối cùng (ghi ra `.cpt`) sẽ báo lỗi.

---

## 2. Bắt đầu

1. Bấm đúp **`DXF_RAMConcept_Suite.exe`**.
2. Tại màn hình chọn, chọn:
   - **Mesh Model Builder** — để tạo model mới từ hình học, hoặc
   - **Area Load Importer** — để thêm tải vùng vào model đã có.

### Đường dẫn dùng chung
File **DXF** và file **CPT output** bạn chọn bên *Mesh Model Builder* sẽ được
ghi nhớ và **tự điền sẵn** bên *Area Load Importer*. Quy trình thường dùng:

1. Dựng model mesh trước (xác định file DXF + file `.cpt`).
2. Mở Area Load Importer — hai đường dẫn đó đã có sẵn, khỏi chọn lại.

---

## 3. Mesh Model Builder (Dựng model mesh)

1. **DXF Drawing File** — chọn file bản vẽ `.dxf`.
2. **RAM Template (.cpt)** *(tùy chọn)* — dựng từ template có sẵn; để trống nếu
   muốn tạo model mới hoàn toàn.
3. **Output File (.cpt)** — nơi lưu model sinh ra.
4. Bấm **Open DXF Layer List…** và gán mỗi layer DXF cho một loại cấu kiện:
   - 🟩 Sàn (Slab)  ·  🟨 Cột (Column)  ·  🟦 Vách (Wall)  ·  🟥 Lỗ mở (Opening)
   - Với sàn có thể đặt thêm chiều dày, TOC và priority.
5. Bấm **Confirm Layer Assignment** (xác nhận gán layer).
6. Bấm **▶ Run Conversion**. Khung **Processing Log** hiển thị từng bước
   (đọc DXF → kết nối API → tạo cấu kiện → mesh → lưu).
7. Khi xong sẽ báo **✓ Done!** và file `.cpt` được ghi ra đường dẫn output.

**Mẹo**
- Cột vẽ bằng hình tròn/chữ nhật được nhận diện tự động; bề dày vách được đo từ
  các cặp đường thẳng song song trong DXF.
- Nếu mesh thất bại, hình học vẫn được lưu — mở `.cpt` trong RAM Concept và chạy
  mesh thủ công.

---

## 4. Area Load Importer (Import tải vùng)

1. **DXF file** — bản vẽ tải `.dxf` (các vùng vẽ bằng polyline/hatch **khép kín**).
2. **CPT file** — model RAM Concept đã có sẵn sàn.
3. Bấm **Read DXF** để nạp các vùng, rồi **Read slab + Auto-align** để lấy đường
   bao sàn từ CPT và tự canh khớp bản vẽ lên sàn.
4. **Canh chính xác (tùy chọn):** bấm **Align 2 points** rồi làm theo 4 bước
   (chọn 2 điểm tương ứng trên DXF và trên đường bao sàn màu đỏ). Công cụ tự giải
   tỉ lệ + offset.
5. **Gán tải:**
   - Click vào 1 vùng (hoặc **Ctrl+click** / **Shift+kéo** để chọn nhiều).
   - Nhập **Load name** (tên tải), **SDL (kN/m²)** và **LL (kN/m²)**.
   - Bấm **Apply to SELECTED region** (vùng đang chọn) hoặc
     **Apply to ALL regions** (tất cả).
   - Màu vùng: **xám** = chưa gán, **xanh** = đã gán, **cam** = đang chọn.
6. Bấm **IMPORT AREA LOAD INTO RAM CONCEPT**. Tải được ghi vào 2 lớp
   `SI Dead Loading` (SDL) và `Live (Reducible) Loading` (LL), rồi lưu `.cpt`.

**Điều khiển khung nhìn:** cuộn chuột = zoom, chuột phải kéo = pan,
**Fit view** để đưa về vừa màn hình.

---

## 4b. Point / Line Load Importer (Import tải điểm / tải đường)

Đọc thẳng **tải điểm (point load)** và **tải đường (line load)** từ chú thích
trong DXF rồi import vào RAM Concept — khỏi click nhập giá trị thủ công.

**Quy ước trong DXF** (theo kiểu chú thích run-length của PTX):
- Tải nằm trên layer **`RUNLENGTH`**.
- **Point load** = `LEADER` (1 mũi tên). Vị trí = đầu mũi tên.
- **Line load** = `DIMENSION` (2 mũi tên). Đoạn tải = 2 điểm đo.
- Hai số cạnh mỗi tải là `TEXT` trên layer **`TEXT_35`**, xếp dọc:
  **số trên = SDL, số dưới = LL**.
- Point load đơn vị **kN**, line load **kN/m**; `Fz` gán **dương**.

**Các bước**
1. **DXF file** / **CPT file** — tự điền sẵn nếu đã dùng các tool kia.
2. (Tùy chọn) đổi **Geometry layer** / **Value text layer** nếu bản vẽ của bạn
   dùng tên layer khác.
3. **Detect loads** — parse DXF; tải tìm được hiện trong log và vẽ lên canvas
   (chấm xanh = point, đường cam = line).
4. **Read slab** — lấy đường bao sàn (đỏ) từ CPT và **canh sơ bộ theo bbox**.
5. Muốn chính xác: bấm **Align 2 points** rồi chọn 2 điểm tải trên DXF + 2 điểm
   tương ứng trên đường bao sàn đỏ (hoặc gõ trực tiếp **Unit scale** và
   **Offset X/Y**). Phép canh này dùng chung với Area Load Importer.
6. **IMPORT POINT/LINE LOADS INTO RAM CONCEPT** — point load dùng
   `add_point_load`, line load dùng `add_line_load`, ghi vào 2 lớp
   `SI Dead Loading` (SDL) và `Live (Reducible) Loading` (LL).

> Luôn kiểm tra canvas (tải nằm đúng trên đường bao sàn đỏ) trước khi import —
> đó là cách bạn xác nhận phép canh đã đúng.

---

## 5. Quy ước dấu / đơn vị

- Nhập **đúng dấu Fz** theo quy ước model (ví dụ tải hướng xuống 0.5 → `-0.5`).
- Tải tính bằng **kN/m²**.
- Mỗi vùng có giá trị khác 0 sẽ tạo một tải SDL và/hoặc một tải LL.

---

## 6. Xử lý sự cố

| Hiện tượng | Nguyên nhân / cách khắc phục |
|------------|------------------------------|
| "Could not load / start RAM Concept" | Chưa cài RAM Concept 2023, hoặc cài ở thư mục khác mặc định. |
| "No CLOSED polyline/hatch found" | Các vùng tải trong DXF không phải hình khép kín. |
| Đường bao sàn đỏ không khớp bản vẽ | Dùng **Align 2 points**, hoặc chỉnh **Offset X/Y** thủ công. |
| Mesh thất bại nhưng file đã lưu | Mở `.cpt` trong RAM Concept và chạy mesh thủ công. |

---

*Đóng gói bằng PyInstaller. Tích hợp sẵn `ezdxf`; dùng Python API của RAM
Concept 2023 lúc chạy.*
