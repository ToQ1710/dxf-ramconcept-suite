# Bộ công cụ DXF → RAM Concept

Một ứng dụng Windows duy nhất gộp **ba công cụ** để đưa dữ liệu kết cấu từ bản
vẽ DXF vào **RAM Concept 2023**:

| Công cụ | Chức năng |
|---------|-----------|
| **Mesh Model Builder** | Đọc bản vẽ DXF, gán layer cho từng cấu kiện (sàn / cột / vách / lỗ mở), tự dò **bề dày + cao độ TOC + drop panel**, rồi sinh model RAM Concept đã chia mesh (`.cpt`). |
| **Area Load Importer** | Đọc bản vẽ tải DXF (vùng hatch), canh khớp lên sàn RAM Concept đã có, gán tải **SDL** và **LL** rồi import vào model. |
| **Point / Line Load Importer** | Đọc thẳng **tải điểm** và **tải đường** từ chú thích DXF rồi import vào model. |

Khi mở app sẽ hiện **màn hình chọn (launcher)** — bấm vào thẻ tương ứng để mở
công cụ cần dùng. Mỗi công cụ mở trong cửa sổ riêng nên có thể chạy cùng lúc.

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
2. Tại màn hình chọn, chọn một trong ba công cụ.

### Đường dẫn dùng chung
File **DXF** và file **CPT output** bạn chọn ở một công cụ sẽ được ghi nhớ và
**tự điền sẵn** sang các công cụ khác. Quy trình thường dùng:

1. Dựng model mesh trước (xác định file DXF + file `.cpt`).
2. Mở các tool tải — hai đường dẫn đó đã có sẵn, khỏi chọn lại.

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

### Tự dò bề dày sàn / cao độ / drop panel
Bật **Auto-detect slab depth & TOC** để app tự chia sàn thành các vùng theo
chú thích trong bản vẽ (chuẩn chú thích PTX):

- **Bề dày**: callout trên layer **`SLAB_DEPTH`** (ưu tiên đích leader = vòng
  tròn khi có, vì hexagon chứa số có thể nằm ở vùng khác và leader trỏ sang
  vùng thật).
- **Cao độ TOC**: nếu có **S.F.L tuyệt đối** (vd `+119.350`) trên layer
  **`STRUCTURAL FINISH FLOOR`** → lấy cao nhất làm chuẩn 0. Nếu không có S.F.L →
  dùng **bước nhảy** giữa các nét **`STEP`** / **`SOFFIT STEP`**. Có cả hai thì
  app kiểm tra chéo và cảnh báo nếu lệch.
- **Drop panel**: rãnh kín trên layer **`SLAB_PANEL`** là vùng drop panel
  authoritative; ngoài ra app tự khép dải pocket quanh leader-circle giữa nét
  STEP và SOFFIT song song. Bề dày panel lấy từ callout bên trong, TOC kế thừa
  vùng bên dưới.
- **Setdown**: giá trị mặc định đọc từ legend `SETDOWN <n>mm U.N.O`.

Tên các layer trên là mặc định chuẩn PTX — nếu bản vẽ dùng tên khác, sửa trong
phần cấu hình layer. Ô **Curved slab edge seg (m)** điều khiển độ mịn khi làm
phẳng biên sàn cong.

**Mẹo**
- Cột vẽ bằng hình tròn/chữ nhật được nhận diện tự động; bề dày vách được đo từ
  các cặp đường thẳng song song trong DXF.
- Nếu mesh thất bại, hình học vẫn được lưu — mở `.cpt` trong RAM Concept và chạy
  mesh thủ công.

---

## 4. Area Load Importer (Import tải vùng)

1. **DXF file** — bản vẽ tải `.dxf` (các vùng vẽ bằng polyline/hatch **khép kín**).
2. **CPT file** — model RAM Concept đã có sẵn sàn.
3. Nạp các vùng tải theo một trong hai cách:
   - **Read DXF** — nạp mọi polyline/hatch khép kín làm vùng tải (gán giá trị
     thủ công sau).
   - **Hatch loads (legend)** — đọc **LOADING LEGEND** trong bản vẽ và **tự gán
     tên + SDL/LL** cho từng vùng hatch theo **màu**. Đây là cách nhanh nhất khi
     bản vẽ có sẵn legend.
4. Bấm **Read slab + Auto-align** để lấy đường bao sàn (đỏ) từ CPT và tự canh
   khớp bản vẽ lên sàn.
5. **Canh chính xác (tùy chọn):** bấm **Align 2 points** rồi làm theo 4 bước
   (chọn 2 điểm tương ứng trên DXF và trên đường bao sàn màu đỏ). Công cụ tự giải
   tỉ lệ + offset.
6. **Gán tải:**
   - Click vào 1 vùng (hoặc **Ctrl+click** / **Shift+kéo** để chọn nhiều).
   - Nhập **Load name** (tên tải), **SDL (kN/m²)** và **LL (kN/m²)**.
   - Bấm **Apply to SELECTED region** hoặc **Apply to ALL regions**.
   - Màu vùng: **xám** = chưa gán, **xanh** = đã gán, **cam** = đang chọn.
7. Bấm **IMPORT AREA LOAD INTO RAM CONCEPT**. Tải được ghi vào 2 lớp
   `SI Dead Loading` (SDL) và `Live (Reducible) Loading` (LL), rồi lưu `.cpt`.

### Tùy chọn về hình học vùng tải
- **Arc segment ≤ (mm)** — bước chia chung khi đọc DXF / lưới conform (mặc định
  **800**).
- **Curve seg ≤ (mm)** — bước chia riêng cho **cung cong** trong tải hatch (mặc
  định **300**, **không nhỏ hơn 300mm**). Cung được tách thành nhiều đoạn thẳng
  ngắn để vùng import giữ đúng hình dạng bản vẽ.
- Hai vùng tải **chung một cung cong** sẽ có **node trùng khít trên cung** (vì
  cung trong DXF giống hệt nhau → tessellate cùng bước cho ra cùng điểm).
- **Subtract base** — trừ tải nền (giá trị base trong legend) khi gán hatch
  load, để mỗi vùng chỉ mang phần tải chênh so với nền.
- **Conform to slab** *(mặc định TẮT)* — ép biên cong của vùng tải vào lưới biên
  sàn. Để **tắt** thì vùng import **giữ đúng hình dạng vùng hatch** (bật lên có
  thể làm méo cạnh thẳng → RAM từ chối). Chỉ bật khi thật sự cần khớp biên cong
  vào sàn.

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

**Tải truyền từ cột/vách tầng trên (DL/LL over)**
Tool còn tự nhận **tải truyền** ghi dạng `DL=950(kN)` / `LL=160(kN)` (trên layer
text) với **leader** chỉ vào cấu kiện tầng trên:
- Mũi tên chỉ vào **WALL OVER** → **line load** rải dọc **đường tâm vách**, giá
  trị = DL/chiều-dài và LL/chiều-dài (kN/m), **làm tròn lên bội số của 5**
  (vd 9→10, 11→15).
- Mũi tên chỉ vào **CO OVER** (cột) → **point load** tại **tâm cột**, giá trị =
  DL và LL (kN).
- Moment `MyEQX/MyEQY` được **bỏ qua** (chỉ gán lực đứng Fz). DL vào lớp
  `SI Dead Loading`, LL vào `Live (Reducible) Loading`.
- Leader nào chỉ vào chỗ không có WALL OVER/CO OVER sẽ báo **unmatched** trong
  log để bạn xử lý tay.

> Luôn kiểm tra canvas (tải nằm đúng trên đường bao sàn đỏ) trước khi import —
> đó là cách bạn xác nhận phép canh đã đúng.

---

## 5. Quy ước dấu / đơn vị

- Nhập **đúng dấu Fz** theo quy ước model (ví dụ tải hướng xuống 0.5 → `-0.5`).
- Tải vùng tính bằng **kN/m²**; tải điểm **kN**; tải đường **kN/m**.
- Mỗi vùng có giá trị khác 0 sẽ tạo một tải SDL và/hoặc một tải LL.

---

## 6. Xử lý sự cố

| Hiện tượng | Nguyên nhân / cách khắc phục |
|------------|------------------------------|
| "Could not load / start RAM Concept" | Chưa cài RAM Concept 2023, hoặc cài ở thư mục khác mặc định. |
| "No CLOSED polyline/hatch found" | Các vùng tải trong DXF không phải hình khép kín. |
| Đường bao sàn đỏ không khớp bản vẽ | Dùng **Align 2 points**, hoặc chỉnh **Offset X/Y** thủ công. |
| Vùng tải import vào bị méo / không thẳng | **Tắt Conform to slab** — vùng sẽ giữ đúng hình dạng hatch. |
| Cung cong import quá thô | Giảm **Curve seg** (tối thiểu 300mm). |
| Một vùng tải không import được | Thường do polygon tự cắt sau khi conform → tắt Conform to slab. |
| Mesh thất bại nhưng file đã lưu | Mở `.cpt` trong RAM Concept và chạy mesh thủ công. |
| Không tự dò được bề dày / TOC | Kiểm tra tên layer `SLAB_DEPTH` / `STRUCTURAL FINISH FLOOR` / `STEP` / `SOFFIT STEP` / `SLAB_PANEL` / `SETDOWN` đúng với bản vẽ. |

---

*Đóng gói bằng PyInstaller. Tích hợp sẵn `ezdxf`; dùng Python API của RAM
Concept 2023 lúc chạy.*
