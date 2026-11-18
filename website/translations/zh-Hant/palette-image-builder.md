# 建立自訂 Modalix 映像

Palette Image Builder（PIB）可為 Modalix 建立自訂 eLxr 映像。它是由 Palette SDK 儲存庫維護的獨立 Docker 容器，透過 sima-cli 安裝，不需要主要的 SDK 容器。

同一個專案可產生兩種部署格式：

- **`.swu`**：用於執行中開發板的已簽署更新套件。
- **`.img.gz`**：用於初始佈建或復原的完整磁碟映像。

## 1. 安裝 PIB

安裝 [sima-cli](https://docs.sima-neat.com/getting-started/installation) 與 Docker 後，執行：

```bash
sima-cli neat install sdk/pib
pib doctor
```


安裝程式會下載符合主機的 x86_64 或 ARM64 容器，並在 Linux、macOS 或 Windows 安裝 `pib` 命令。若 PATH 已更新，請開啟新的終端機。PIB 使用 Linux 容器；Docker 必須正在執行，並允許建立映像所需的特權存取。x86 Docker 主機會自動設定內附的 ARM64 模擬器。

本機專案資料夾須為 `minimal` 保留至少 10 GiB、`palette` 至少 20 GiB 可用空間，Docker 儲存空間也須有相近容量。建置時必須能連線至 Debian/eLxr 與 SiMa 套件儲存庫。產生的開發板映像架構為 ARM64。

`sdk/pib` 會選取 main 最新發佈的套件。若要指定其他 SDK 分支或版本，使用相同的 SDK 語法，例如 `sima-cli neat install sdk/pib@develop`。手動 Docker 安裝與主機需求請參閱[安裝參考](palette-image-builder-reference.md#installation)。

## 2. 建立映像專案

```bash
pib init my-image --flavor minimal
cd my-image
```


若需要桌面環境與較多套件，請使用 `--flavor palette`。映像的平台版本由所選容器決定。專案包含：

```text
my-image/
├── image.yaml       # version and customizations
├── custom-debs/     # your ARM64 or architecture-independent Debian packages
├── overlay/         # files to add to the root filesystem
├── hooks/           # optional post-install scripts
├── keys/            # your signing identity and public trust material
├── configs/         # release-specific board defaults; normally leave unchanged
└── out/             # generated artifacts
```


後續命令都在此專案目錄執行。使用 `pib shell` 開啟已掛載專案檔案的容器殼層，在裡面直接執行 `pib`，再以 `exit` 返回主機。

若要使用包含應用程式套件、設定覆蓋層與服務啟用掛鉤的完整範例，請改用 `pib init my-image --example custom-image`。[範例教學](palette-image-builder-example.md)說明完整流程；CI 也會在兩種架構上使用儲存庫中相同的 `image.yaml` 建置。範例已包含在容器中，不必複製原始碼儲存庫。

## 3. 首次設定簽署身分

為開發建立測試 CA 與簽署身分：

```bash
pib keys init --cn 'My Company Development'
```


設定完成後，將 `keys/ca.key` 移至安全的離線位置。簽署用終端憑證與私密金鑰仍保留在 `keys/`；產生的 `.gitignore` 會排除私密金鑰與建置輸出。請安全備份簽署資料。既有開發板信任此 CA，因此移至新專案或平台版本時仍須保留相同 CA。

正式環境請使用組織的簽署身分，詳見[外部金鑰與憑證更新](palette-image-builder-reference.md#signing)。容器不包含 SiMa 的正式簽署金鑰。

## 4. 自訂映像

第一次建置可先用編輯器建立 `overlay/etc/motd`：

```text
My custom Modalix image
```


`overlay/` 內的檔案會保留權限，並在映像中成為 root 所有。覆蓋層在套件安裝前套用，因此套件可能取代 `/etc` 以外的檔案。必須在安裝後執行的變更請使用掛鉤。

若要以 Debian 套件安裝應用程式：

```bash
cp /path/to/my-app_1.0_arm64.deb custom-debs/
pib sign-debs
pib verify-debs
```


在 `image.yaml` 中加入**套件名稱**，而不是檔案名稱：

```yaml
packages:
  add: [my-app]
  remove: []
```


套件必須使用 `arm64` 或 `all` 架構。核心替換、套件移除、服務啟用與自訂更新指令碼請參閱[自訂參考](palette-image-builder-reference.md#customization)。

## 5. 建置已簽署更新

```bash
pib build --sign
```


這會建置映像、以設定的簽署身分簽署 SWU，並驗證簽章、承載內容雜湊與建置資訊清單。通常需要數分鐘，依主機與網路而定。結果位於 `out/`，包含：

| 輸出 | 用途 |
|---|---|
| `*.swu` | 已簽署更新套件 |
| `*.unsigned.swu` | 供獨立簽署階段使用的套件 |
| `*.img.gz` | 佈建／復原用壓縮磁碟映像 |
| `*-boot0.be` | 對應的 tRoot 承載內容 |
| `*.manifest.json` | 套件版本／來源與開機承載內容的來源資訊 |
| `*.cdx.json` | CycloneDX 軟體物料清單 |
| `SHA256SUMS` | 成品校驗碼 |

若要再次驗證而不必自行尋找檔案名稱：

```bash
pib verify
```


CI 或獨立簽署系統可分別執行 `pib build`、`pib sign` 與 `pib verify`。即使 `out/` 有舊版本，後兩者仍會選取目前 `image.yaml` 的版本。

下一次建置前，請增加 `image.yaml` 中 `version` 的最後一個數字，例如從 `3.0.0.1` 改為 `3.0.0.2`。重建相同版本會取代其輸出，包括現有已簽署 SWU。開發板會強制執行映像版本原則。

## 6. 準備部署

建置與驗證更新套件不會修改開發板。部署前請完成：

- 若要寫入全新開發板，先設定首次開機存取。預設 `root` 與 `sima` 帳號鎖定；更新時可能保留舊板的認證資訊。請參閱[開發板存取](palette-image-builder-reference.md#board-access)。
- 透過經授權的開發板佈建流程設定 CA。原廠開發板不會自動信任您剛建立的 CA。
- `.swu` 使用 SWUpdate；`.img.gz` 與必要開機承載內容則使用平台已驗證的媒體寫入／復原程序。

SSH 更新命令請參閱[安裝 SWU](palette-image-builder-reference.md#installing-an-swu)。正式使用前，先在可復原的開發板上驗證自訂映像。

## 疑難排解

- **無法存取迴路裝置或 device-mapper：** 執行 `pib doctor`。啟動器會提供所需特權，但 Linux Docker 主機仍須提供這些裝置。
- **x86 上 ARM64 設定失敗：** PIB 會自動註冊內附模擬器。請確認 Linux Docker 引擎允許特權 binfmt 存取。
- **映像建置中斷：** 先停止建置，以 `pib clean` 檢查剩餘資源，再以 `pib clean --yes` 移除。清理可能包含同一 Docker 主機上的其他 PIB 專案。
- **套件／bootstrap 失敗：** 檢查 `configs/images/mmdebstrap.log`。建置期間須能連線至套件儲存庫。
- **新平台版本：** 使用對應容器建立新專案，保留既有 CA，並移入相容套件與自訂內容。請參閱[升級參考](palette-image-builder-reference.md#new-platform-release)。
