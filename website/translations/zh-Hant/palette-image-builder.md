# 自訂映像工作流程

使用 Palette SDK 的搭配工具 Palette Image Builder（PIB），將軟體與系統設定組成自訂 Modalix eLxr 映像。本頁說明整體流程。完整的套件、服務與覆蓋檔案實作步驟，請參閱[範例映像](palette-image-builder-example.md)。

## 安裝 PIB

安裝 [sima-cli](https://docs.sima-neat.com/getting-started/installation)，啟動使用 Linux 引擎的 Docker，再執行：

```bash
sima-cli neat install sdk/pib
```


安裝程式會選擇主機對應的 x86_64 或 ARM64 容器、設定啟動器與 PATH，並自動檢查 Docker 主機。若 PATH 有更新，請開啟新終端機。執行 PIB 不需要主 SDK 容器。

建立映像需要 Docker 特權存取、套件庫連線，以及專案與 Docker 儲存空間。`minimal` 請預留 10 GiB，`palette` 請預留 20 GiB。x86 主機會自動設定 ARM64 模擬。支援平台、其他版本與手動安裝方式，請參閱[安裝參考](palette-image-builder-reference.md#installation)。

## 1. 建立映像專案

```bash
pib init my-image --flavor minimal
cd my-image
```


選擇與平台版本相容的映像種類。需要桌面與較完整套件集時，使用 `palette`。`configs/` 中的版本專用板卡預設值由選定的建置器提供，通常不需修改。後續命令皆在專案目錄執行。

## 2. 定義映像內容

| 輸入 | 用途 |
|---|---|
| `image.yaml` | 映像種類、平台版本、映像版本、套件與簽署設定 |
| `custom-debs/` | ARM64 或架構無關的 Debian 套件 |
| `overlay/` | 複製到根檔案系統的設定與其他檔案 |
| `hooks/` | 套件安裝後的變更，例如啟用服務 |

使用 Palette SDK 建置應用程式並編譯模型，再將目標所需檔案打包。PIB 負責組合套件，不編譯應用程式原始碼。各元件的角色請參閱 [Palette SDK 系統堆疊](sdk-architecture.md)。

`image.yaml` 應列出 Debian 套件名稱，而非 `.deb` 檔名。檔案使用覆蓋目錄，安裝後變更使用掛鉤。套件、核心與掛鉤的詳細規則請參閱[自訂設定參考](palette-image-builder-reference.md#customization)。

## 3. 準備簽署與信任

開發時，為專案建立一次簽署身分：

```bash
pib keys init --cn 'My Company Development'
```


設定完成後，請離線保存 CA 私密金鑰。更新現有板卡時保留同一 CA；出貨映像應使用組織的正式簽署程序。外部金鑰、憑證更新及分離建置與簽署流程，請參閱[簽署參考](palette-image-builder-reference.md#signing)。

## 4. 設定板卡登入

**若要使用 UART／主控台密碼登入，請在建置前設定 `PIB_CREDENTIALS`。** 建立簽署金鑰不會設定登入密碼。若未提供此檔案，新映像的 `root` 與 `sima` 密碼都會鎖定，因此即使 SSH 金鑰存取正常，主控台密碼登入仍會失敗。

在專案目錄中使用主機的 OpenSSL，產生含有密碼雜湊的受保護檔案。先輸入並確認 `root` 密碼，再輸入並確認 `sima` 密碼：

```bash
mkdir -p ../secure
chmod 700 ../secure
(umask 077; printf 'root:%s\nsima:%s\n' \
  "$(openssl passwd -6)" "$(openssl passwd -6)" > ../secure/credentials)
chmod 600 ../secure/credentials
export PIB_CREDENTIALS="$(cd ../secure && pwd)/credentials"
```

將此檔案保存在專案與版本控制之外。在同一個 Shell 執行建置；若開啟新 Shell，請重新 export `PIB_CREDENTIALS`。PIB 於建置時以唯讀方式掛載此檔案。

若只需要 SSH 金鑰存取，可略過認證檔案，並在建置前加入核准的公開金鑰，請參閱[板卡存取](palette-image-builder-reference.md#board-access)。設定 root 密碼後，root SSH 仍僅允許金鑰驗證。更新既有板卡時，持久覆蓋層可能保留舊認證資料。

## 5. 建置並驗證

若專案包含自訂 Debian 套件，請在建置映像前簽署並驗證：

```bash
pib sign-debs
pib verify-debs
pib build --sign
pib verify
```


建置會建立新的根檔案系統、套用專案輸入、產生部署檔案，並簽署及驗證 SWU。結果、套件清單、SBOM 與檢查碼都儲存在 `out/`。

## 6. 部署與維護

| 產物 | 部署用途 |
|---|---|
| 已簽署的 `.swu` | 更新運作中的板卡 |
| `.img.gz` | 初始磁碟佈建或復原 |

部署前請準備板卡存取方式並建立 CA 信任。遵循[板卡存取](palette-image-builder-reference.md#board-access)與 [SWU 安裝](palette-image-builder-reference.md#installing-an-swu)程序；建置成功不代表板卡已變更或通過驗證。

請在可復原的硬體上驗證映像，並保留清單、檢查碼與簽署身分。後續更新請提高映像版本；更換平台版本時，將相容輸入遷移至新專案。請參閱[平台升級參考](palette-image-builder-reference.md#new-platform-release)。

開機分割區、rootfs 槽位與資料空間配置，請參閱[媒體與分割區配置](palette-image-builder-reference.md#media-and-partition-layout)。

## 繼續閱讀範例或參考文件

- [範例映像](palette-image-builder-example.md)：逐步建置內附的應用程式套件、設定與服務。
- [Palette Image Builder 參考](palette-image-builder-reference.md)：命令、自訂規則、簽署、疑難排解與板卡操作。
