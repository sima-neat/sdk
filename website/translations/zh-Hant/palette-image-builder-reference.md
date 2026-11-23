# Palette Image Builder 參考

請先閱讀[自訂映像工作流程](palette-image-builder.md)。此頁說明選用功能與開發板操作；容器維護請參閱[建置工具 README](../palette-image-builder/README.md)。

## 安裝

標準安裝命令是 `sima-cli neat install sdk/pib`。它會讀取所選 SDK 發佈項目的 `pib/` 中繼資料，取得已驗證的多平台映像，並安裝可攜式主機啟動器。Python 來自 sima-cli 環境，建置工具保留在容器內。預設使用 main，`sdk/pib@develop` 與 `sdk/pib@<release>` 可選取其他發佈項目。

Windows 請使用 PowerShell，並將 Docker Desktop 設為 Linux 容器模式。安裝程式會建立 `pib.cmd` 並更新使用者 PATH。Linux/macOS 則安裝至 `~/.local/bin`，必要時更新殼層設定。各平台皆自動選取 amd64/arm64 映像。Linux Docker 主機須支援迴路裝置、device-mapper 與 binfmt_misc；桌面虛擬機也須提供這些功能。`pib doctor` 可執行檢查。完整映像建立已在原生 Linux x86/ARM 及 Apple Silicon/Colima 驗證。Windows 安裝測試不代表 Windows 完整映像建立已完成驗證。

若不使用 sima-cli，可手動取得公開 Docker 映像並擷取啟動器。PATH 中須有 Python 3：

```bash
export PIB_IMAGE=ghcr.io/sima-neat/palette-image-builder-develop:latest
docker pull "$PIB_IMAGE"
mkdir -p "$HOME/.local/bin"
docker run --rm --entrypoint cat "$PIB_IMAGE" \
  /usr/local/share/pib/host/pib > "$HOME/.local/bin/pib"
chmod +x "$HOME/.local/bin/pib"
export PATH="$HOME/.local/bin:$PATH"
pib doctor
```


x86 映像已內附模擬器。特權 PIB 啟動時，只在缺少可用 ARM64 處理常式時向 Docker 主機 Linux 核心註冊。既有正常處理常式會保留；原生 ARM64 不需註冊。Docker 主機重啟後也會自動重新設定，不會在主機安裝套件。

## 環境變數

在執行 `pib` 的主機 Shell 設定。檔案必須可供 Docker 存取。認證與簽署檔案僅以唯讀方式掛載至使用它們的命令。`PIB_CONFIGS` 以唯讀方式掛載上層目錄；`PIB_DEB_CACHE` 可寫入。

| 變數 | 使用命令 | 用途 |
|---|---|---|
| `PIB_IMAGE` | 所有命令 | 以指定標籤或摘要覆寫已安裝的容器映像。 |
| `PIB_CREDENTIALS` | `pib build` | 含有 `root:<hash>` 與 `sima:<hash>` 密碼雜湊的檔案。未設定時新映像鎖定兩個密碼；既有板卡可能透過持久覆蓋層保留認證資料。 |
| `SWU_SIGNING_KEY`, `SWU_SIGNING_CERT` | `pib sign`, `pib build --sign` | 外部簽署金鑰與憑證。金鑰也可為 `pkcs11:` URI。預設來自專案設定；憑證必須連結至映像信任的 CA。 |
| `PIB_CONFIGS` | `pib init` | 進階：使用外部映像設定目錄取代內附設定。 |
| `PIB_PCSCD_DIR` | 簽署命令 | 覆寫 pcscd 通訊端目錄，預設 `/run/pcscd`。Linux 容器必須能存取通訊端。 |
| `PIB_DEB_CACHE` | `pib build`, `pib shell` | 已驗證 Debian 下載檔的主機快取。每次建置都依已認證中繼資料檢查雜湊與大小。 |
| `PIB_SBP_KERNEL_URL`, `PIB_SBP_KERNEL_REF` | `pib sbp` | 每次執行時要建置的核心儲存庫（不含認證資訊的 https URL）與分支或提交。`--kernel-url` 與 `--kernel-ref` 可針對單次執行覆寫這兩個變數。 |
| `PIB_SBP_KERNEL_SRC` | `pib sbp` | 主機上存放您核心的 Git 儲存庫，可為簽出目錄或 bare 儲存庫；以唯讀方式掛載。適用於私人儲存庫，或尚未推送到任何地方的提交。 |
| `PIB_SBP_SRC` | `pib sbp` | 包含 sbp（`pkgbuild/`）及其套件設定（`configs/packages/`）的簽出目錄，用來取代套件建置器映像內附的版本；在映像內含這些內容之前為必要設定。只會以唯讀方式掛載這兩個目錄。 |
| `PIB_SBP_IMAGE` | `pib sbp` | 覆寫套件建置器映像。預設為與 `PIB_IMAGE` 一同發佈的映像（相同標籤加上 `-sbp`），或安裝時繫結的映像。 |
| `PIB_SBP_JOBS`, `PIB_SBP_CCACHE_SIZE`, `PIB_SBP_VOLUME` | `pib sbp` | 平行編譯工作數；編譯器快取大小（預設 `5G`）；存放 sbp 工作目錄、套件庫與快取的 Docker 磁碟區（預設 `pib-sbp-<uid>`）。 |

## 命令

映像壓縮使用 pigz，充分利用建置主機可用的 CPU 核心。輸出仍相容 gzip；簽署與驗證涵蓋實際壓縮後的承載內容。

若要在多次建置間重用 Debian 下載，請先設定主機快取目錄：

```bash
export PIB_DEB_CACHE="$HOME/.cache/sima/pib-debs"
pib build --sign
```


快取只保存套件位元組。每次 bootstrap 都會下載並驗證當前儲存庫中繼資料，再依 SHA256 與大小檢查快取。損壞資料會捨棄並重新下載。根檔案系統、套件安裝、自訂掛鉤、簽署與驗證每次都重新執行。快取可能包含自訂套件，請放在自己的使用者目錄。

| 命令 | 用途 |
|---|---|
| `pib doctor` | 檢查工具、空間、迴路裝置、device-mapper 與模擬功能 |
| `pib init DIR --flavor minimal` | 建立專案；支援 minimal、palette |
| `pib init DIR --example custom-image` | 複製完整範例規格與輸入 |
| `pib shell` | 開啟已掛載目前專案的容器殼層 |
| `pib keys init --cn NAME` | 產生 CA、SWU 終端憑證與 Debian 簽署身分 |
| `pib keys renew --cn NAME` | 使用同一 CA 更新終端憑證 |
| `pib keys fit` | 產生金鑰組，用於簽署 `pib sbp` 建置的核心 FIT 映像 |
| `pib sbp package -p linux` | 建置核心及 palette 的核心模組套件，輸出至 `custom-debs/` |
| `pib sign-debs` / `pib verify-debs` | 簽署／檢查自訂 Debian 套件 |
| `pib build [--sign] [--supplier NAME]` | 建置，並可選擇簽署與驗證 |
| `pib sign [FILE]` | 簽署套件；預設使用目前專案版本 |
| `pib verify [FILE] [--ca CRT] [--manifest JSON]` | 驗證簽章與承載內容，自動選用專案預設值與相鄰資訊清單 |
| `pib diff --against MANIFEST` | 顯示與先前建置的套件差異 |
| `pib clean [--yes]` | 檢查／移除殘留建置迴路裝置與磁碟區群組 |

所有命令均在容器內執行。主機啟動器僅處理 Docker、工作區掛載與明確指定的外部檔案。`build`、`doctor`、`clean` 與互動殼層使用特權裝置存取；簽署、驗證、金鑰產生與專案建立不需要。`pib sbp` 在專屬映像中以非特權方式執行，看到的專案內容除 `custom-debs/` 外皆為唯讀；在 `keys/` 中，它只看得到核心 FIT 金鑰組。

## 建置產物

| 檔案 | 技術用途 |
|---|---|
| `*.swu` | 已簽署的更新套件 |
| `*.unsigned.swu` | 獨立簽署階段的輸入 |
| `*.img.gz` | 佈建或復原用的壓縮磁碟映像 |
| `*-boot0.be` | 相關 tRoot 內容，請遵循平台佈建程序 |
| `*.manifest.json` | 套件版本、來源與開機內容的來源紀錄 |
| `*.cdx.json` | CycloneDX 軟體物料清單 |
| `SHA256SUMS` | 產物檢查碼 |

即使 `out/` 含有舊版建置，`pib sign` 與 `pib verify` 仍會選擇目前 `image.yaml` 的版本。重建相同版本會取代其產物，包括已簽署的 SWU。後續更新請提高版本。

## 媒體與分割區配置

Modalix eMMC/SD 映像使用 GPT 開機分割區，以及存放根檔案系統和資料的 LVM 分割區。下列數值是目前 PIB 平台版本（`3.0.0`）的預設值，並非所有版本都固定如此。確切配置請查看所選建置器的 `configs/images/image-params.yaml` 與 `image-stages.yaml`。首次開機時，LVM 分割區與資料磁碟區會擴展至裝置可用容量，因此下載的磁碟映像可能小於實體裝置。

### 實體分割區

| # | 名稱 | 大小 | 格式 | 內容 |
|---|---|---|---|---|
| 1 | `boot.A` | 256 MiB | vFAT | A 槽的 `fip.bin`、U-Boot、開機指令碼、核心 FIT／裝置樹資料及 U-Boot 環境 |
| 2 | `boot.B` | 256 MiB | vFAT | B 槽的開機產物 |
| 3 | `lvm` | 首次開機擴展後剩餘的裝置可用容量 | LVM 實體磁碟區 | 包含下列邏輯磁碟區 |

### 邏輯磁碟區

邏輯磁碟區位於分割區 3 內。

| 磁碟區 | 大小 | 檔案系統 | 用途 |
|---|---|---|---|
| `rootfs.A` | `minimal` 為 1.5 GiB；`palette` 為 5.5 GiB | ext4 | A 槽根檔案系統 |
| `rootfs.B` | 與 `rootfs.A` 相同 | 寫入內容後為 ext4 | B 槽根檔案系統，初始內容取決於 `slots` |
| `data` | 為兩個 rootfs 槽預留空間後剩餘的 LVM 容量 | ext4 | 一般儲存空間，首次開機時擴展 |

### 槽位初始內容

- **`slots: ab`（PIB 預設）：** 在磁碟映像中建立兩個 rootfs 磁碟區並寫入內容。
- **`slots: a`：** 磁碟映像只包含 `rootfs.A`。首次開機時，`simaai-growlvm` 會先建立與其相同大小的 `rootfs.B`，再擴展 `data`。更新寫入內容前，B 槽沒有根檔案系統。

`slots` 控制初始磁碟映像內容，不會移除 A/B 更新支援。更新會寫入非作用中槽位。更新後，兩槽的開機產物與根檔案系統可能不同。

## 疑難排解

- **缺少 loop 或 device-mapper 存取：** 執行 `pib doctor`。Docker 必須提供所需裝置並允許特權容器。
- **x86 上 ARM64 設定失敗：** 確認 Linux Docker 引擎允許特權 binfmt 註冊。
- **映像建置中斷：** 停止建置，使用 `pib clean` 檢視殘留資源，再視需要使用 `pib clean --yes`。清理可能影響同一主機上的其他 PIB 專案。
- **套件或初始檔案系統建立失敗：** 檢查 `configs/images/mmdebstrap.log` 與套件庫連線。

## 自訂

編輯 `image.yaml`。除非正在開發開發板支援，否則保留 `configs/` 中的版本預設值。

```yaml
base: minimal
release: 3.0.0
version: 3.0.0.2
packages:
  add: [my-app]
  remove: []
overlay: overlay/
hooks: [hooks/enable-my-app.sh]
vendor: My Company
```

覆蓋檔案會保留權限，並在映像中成為 root 所有。覆蓋內容在套件安裝前套用，因此套件可能取代 `/etc` 以外的檔案。必須在套件安裝後執行的變更，請使用安裝後掛鉤。


建立安裝後掛鉤以啟用應用程式服務：

```sh
#!/bin/sh
set -eu
systemctl --root="$1" enable my-app.service
```


掛鉤會在 SiMa 掛鉤與套件安裝後，依序透過 `sh` 執行。`$1` 是 rootfs 目錄。請寫入該目錄下，或使用 `systemctl --root="$1"`；`chroot "$1"` 會執行映像中的 ARM64 程式。掛鉤使用工作區相對路徑，字元限英數字與 `_ . / + -`。

移除其他套件需要的依賴項目會使 APT 解析失敗。請保留開發板掛鉤需要的套件，例如 `swupdate` 與 palette 的 `kea`。從 `palette` 改成 `minimal` 也會改變映像大小與預設套件。

自訂 Debian 套件需要可由 `image.yaml` 的 `debs.key` 接受的分離式簽章。`pib sign-debs` 使用產生的 Debian 簽署金鑰。若使用既有 GPG 身分，將公開金鑰匯出到 `keys/debs-signing.asc`，於外部簽署套件，並在建置前執行 `pib verify-debs`。

核心套件另有規則：保留 `configs/images/image-params.yaml` 中的版本核心套件名稱。PIB 會自動選取，且只能安裝一個核心。`pib sbp` 會從 SiMa 的核心原始碼或您自己的原始碼建置這類套件，請參閱[建置核心](#building-the-kernel)。本機替換的 tRoot、ATF、U-Boot 套件會被拒絕。套件的 U-Boot 必須與 `fip.bin` 中的內容相符。

自訂 `swu.description` 與 `swu.script` 可取代更新指示。請先複製 `configs/images/files/` 的版本預設值，保留版本／硬體相容性預留位置、雜湊與必要開機／SBOM 成員。這些指令碼在安裝時於開發板執行，請在可復原的板子測試變更。

`--dev` 建置使用臨時身分，不能與一般交付用的 `--sign` 合用。開發產生的客戶 CA／終端金鑰與 `--dev` 模式是不同概念。

## 建置核心

`pib sbp` 使用 SiMa 的套件建置器 sbp，從 SiMa 公開的核心原始碼或您自己的原始碼建置 Modalix 核心，並將核心的 Debian 套件放入 `custom-debs/`。對於 palette 專案，它也會針對該核心重新建置 palette 映像所含的核心模組套件 smifb 與 lttng-modules。它在含有 ARM64 交叉工具鏈的獨立套件建置器映像中執行；Docker 會在首次使用時下載此映像（約 2.5 GB）。

```bash
pib keys fit
pib sbp package -p linux
pib sign-debs
pib build --sign
```


`pib keys fit` 會建立 `keys/fit-signing.key` 與 `keys/fit-signing.crt`，只需執行一次；`pib sbp` 會以該金鑰簽署核心的 FIT 映像。接著選擇原始碼來源：

| 核心原始碼 | 選取方式 |
|---|---|
| SiMa 的公開儲存庫，`master` 分支 | 預設：`https://github.com/SiMa-ai/simaai-linux.git` |
| 您的 fork、其中一個分支或某個提交 | `--kernel-url https://github.com/<you>/simaai-linux.git --kernel-ref <branch>`，或 `PIB_SBP_KERNEL_URL` 與 `PIB_SBP_KERNEL_REF` |
| 您電腦上的儲存庫 | `PIB_SBP_KERNEL_SRC=<path>`：其目前簽出的分支，或 `PIB_SBP_KERNEL_REF` |

每次執行都會查詢該分支並建置其最新提交，`pib sbp` 會顯示該提交；分支有變動時，核心會重新建置。只會建置已提交的變更，`pib sbp` 會對未提交的變更發出警告。建置容器不含任何認證資訊：公開儲存庫請以不含權杖的 https URL 指定，私人儲存庫則以 `PIB_SBP_KERNEL_SRC` 指定，該儲存庫會以唯讀方式掛載。首次從某個儲存庫建置時，會下載整個儲存庫。

請保留平台版本的核心版本（6.18.3）、其 `simaai_modalix_defconfig` 設定，以及 SiMa 的 FIT 封裝。映像只會安裝平台版本的核心套件名稱，因此其他版本的核心不會納入。不含 FIT（`boot/fitImage`）的核心套件會以未簽署的一般核心映像開機，`pib sbp` 會對此發出警告。它也會將核心的 SiMa 專用標頭檔與平台版本的標頭檔比較，並在兩者不同時發出警告；SiMa 預先建置的軟體（例如相機 ISP 與 MLA 執行階段）皆依據平台版本的標頭檔建置。`master` 分支目前存放 SiMa 的 2.1.3 核心，既沒有 FIT 封裝，也缺少部分目前的標頭檔，因此在 SiMa 於該分支發佈目前的核心之前，這兩項警告都會出現。

核心建置約需半小時，並在 Docker 磁碟區 `pib-sbp-<uid>` 中佔用 6-8 GB。在 sbp 本身納入套件建置器映像之前，請將 `PIB_SBP_SRC` 設為包含 sbp 的簽出目錄（`pkgbuild/` 與 `configs/packages/`）。

## 簽署

映像將 `signing.ca` 嵌入為更新信任根。更新既有開發板時請保留該 CA。使用工作區外部金鑰的方法：

```bash
cp /path/to/public-ca.crt keys/ca.crt
SWU_SIGNING_KEY=/path/to/private-signing.key \
SWU_SIGNING_CERT=/path/to/public-signing.crt pib sign
pib verify
```


啟動器只會唯讀掛載各選定檔案，不會掛載整個目錄。`pib build --sign` 也接受這些變數。若要加強分離，可將簽署私密金鑰保留在獨立簽署電腦，分別執行建置與簽署。CA 私密金鑰只用於發行／更新終端憑證，請離線保管，不要放在日常建置專案內。

若要更新產生的終端憑證，暫時將 `ca.key` 放回 `keys/`，使用與初次設定相同的演算法執行 `pib keys renew --cn 'My Company Development'`，再把 CA 金鑰移回離線儲存。終端憑證有效期為 825 天。

PKCS#11 使用 `pib sign --pkcs11 'pkcs11:...' --cert keys/swu-signing.crt`。Docker 主機需要 pcscd 與讀卡機驅動程式。啟動器於簽署時掛載可用的 pcscd 通訊端，`PIB_PCSCD_DIR` 可改寫其位置。本移植未測試實體卡片／權杖；macOS 主機通訊端不一定可由 Linux Docker VM 存取。

若要加密承載內容，執行 `pib keys payload`，建置前設定 `encryption: {key: keys/payload.key}`，再使用 `pib sign --encrypt`。產生的映像包含解密金鑰，因此無法防止可擷取映像的人取得內容。加密須分開執行建置與簽署；`build --sign` 使用一般未加密的簽署流程。

## 開發板存取

全新寫入前，先設定認證資訊或授權 SSH 金鑰。若要提供 root 與 sima 密碼雜湊，在專案外建立受保護檔案並透過 `PIB_CREDENTIALS` 指定：

```bash
mkdir -p ../secure
chmod 700 ../secure
(umask 077; printf 'root:%s\nsima:%s\n' \
  "$(openssl passwd -6)" "$(openssl passwd -6)" > ../secure/credentials)
PIB_CREDENTIALS="$(cd ../secure && pwd)/credentials" pib build --sign
```


此選用方式需要主機上的 OpenSSL。密碼以提示輸入，只儲存雜湊。root SSH 仍僅允許金鑰存取。也可將核准公開金鑰放在 `overlay/root/.ssh/authorized_keys`，目錄權限設 700、檔案設 600。每塊板子於首次開機產生自己的 SSH 主機金鑰。

若需要 root SSH 存取，請在建置前於專案目錄執行下列命令。僅附加核准的**公開金鑰**；勿將私密金鑰放入映像。

```bash
mkdir -p overlay/root/.ssh
chmod 700 overlay/root/.ssh
cat "$HOME/.ssh/id_ed25519.pub" >> overlay/root/.ssh/authorized_keys
chmod 600 overlay/root/.ssh/authorized_keys
```

即使 `PIB_CREDENTIALS` 設定了 root 密碼，SSH 的 root 密碼驗證仍停用。每行授權一把公開金鑰。部署後可使用核准的金鑰連線至 `ssh root@<board-address>`。既有板卡可能透過持久覆蓋層保留 SSH 設定。

## 安裝 SWU

下列命令會修改開發板。請明確選擇**已簽署** `.swu` 與預期的板子。開發板須執行相容的 SiMa/PIB eLxr 映像，並提供 `sima` 的 SSH 與 sudo 存取。

第一次安裝須經授權佈建程序建立 CA 信任。指南中的開發板初始設定如下：

```bash
BOARD=192.0.2.10
SWU=out/your-image.swu
scp "$SWU" keys/ca.crt "sima@$BOARD:/tmp/"
ssh -t "sima@$BOARD" sudo swupdate -i "/tmp/$(basename "$SWU")" \
  -k /tmp/ca.crt -e update,full
ssh -t "sima@$BOARD" sudo reboot
```


後續更新使用板上已安裝的 CA 與版本原則：

```bash
scp "$SWU" "sima@$BOARD:/tmp/"
ssh -t "sima@$BOARD" sudo simaai-update "/tmp/$(basename "$SWU")" -e update,full
ssh -t "sima@$BOARD" sudo reboot
```


更新目標為非作用中槽位。開機選取與 watchdog 回復取決於平台開機／更新實作，需對您的映像進行硬體驗證。預設更新保留開發板的可寫入覆蓋層；清除覆蓋層的更新可能移除本機認證資訊與設定。首次 eMMC 寫入請遵循平台復原指南；SWU 不是 raw 磁碟映像。

目前 PIB 配置使用 GPT `boot.A`、`boot.B`，以及包含 rootfs A/B 和資料的 LVM 分割區。不要在此配置套用舊版 raw 分割區 U-Boot 寫入指示。確切幾何配置以版本的開發板範本為準。

## 新平台版本

取得適當的建置工具映像並擷取啟動器，再以 `pib init` 建立全新專案。保留原始 CA 與簽署身分，移入覆蓋層／掛鉤，並將客戶設定合併到新 `image.yaml`，保留新的 `release` 與 `version` 值。

只複製與新平台相容的 Debian 套件。自訂更新指令碼／描述須以該版本預設值為基礎更新。不要用舊 `configs/` 整批覆蓋新目錄。維護舊版本時，請保留原專案與固定版本的啟動器／映像參照。
