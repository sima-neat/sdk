# 範例映像

本教學會建立已簽署的 Modalix 映像，包含小型應用程式、設定檔與自動啟動服務。PIB 已內附完整範例，不必複製儲存庫或在電腦上安裝建置工具。CI 也會在 x86 與 ARM64 測試相同映像規格。

開始前請依[自訂映像工作流程](palette-image-builder.md#install-pib)安裝 PIB。本頁專注於內附範例的檔案與命令。

## 1. 將範例複製到專案

```bash
pib init my-custom-image --example custom-image
cd my-custom-image
```


您會自訂下列檔案：

| 檔案 | 用途 |
|---|---|
| `image.yaml` | 映像類型、版本、套件、覆蓋層、掛鉤與簽署設定 |
| `package-root/usr/bin/pib-example-app` | 範例 Debian 套件安裝的應用程式 |
| `package-root/DEBIAN/control` | 套件名稱、版本與架構 |
| `overlay/etc/pib-example.conf` | 複製到映像的應用程式設定 |
| `overlay/etc/systemd/system/pib-example.service` | 服務定義 |
| `hooks/enable-example.sh` | 啟用服務並寫入建置標記 |

若要開啟容器內的 Linux 殼層：

```bash
pib shell
```


專案會掛載於 `/workspace`。執行 `exit` 返回電腦。其餘命令都在電腦上的專案目錄執行，每個 `pib` 命令都會自動啟動容器。

## 2. 建立開發簽署身分

```bash
pib keys init --cn 'My Company Development'
```


這會建立 CA、SWU 簽署憑證與私密金鑰，以及自訂 Debian 套件的簽署身分。完成後將 `keys/ca.key` 移至專案外的安全位置。更新既有開發板時請維持相同 CA。正式出貨映像應使用組織的正式簽署流程。

## 3. 封裝並簽署應用程式

在 PIB 中建置套件，然後簽署並驗證：

```bash
pib shell -c 'dpkg-deb --root-owner-group --build package-root custom-debs/pib-example-app_1.0.0_all.deb'
pib sign-debs
pib verify-debs
```


範例是殼層指令碼，因此使用架構 `all`。編譯的 Modalix 應用程式通常須透過 SDK 為 `arm64` 建置。PIB 接受 ARM64 或架構無關套件，不會交叉編譯應用程式原始碼。

## 4. 檢查映像規格

範例包含以下自訂設定：

```yaml
base: minimal
target: modalix
slots: ab
release: 3.0.0
version: 3.0.0.1
vendor: PIB Example
packages:
  add: [pib-example-app]
  remove: []
overlay: overlay/
hooks: [hooks/enable-example.sh]
signing:
  ca: keys/ca.crt
  cert: keys/swu-signing.crt
  key: keys/swu-signing.key
debs:
  key: keys/debs-signing.asc
```


套件清單使用 Debian 套件名稱，而不是 `.deb` 檔案名稱。可用編輯器修改 `overlay/etc/pib-example.conf`，嘗試自己的設定。掛鉤會在套件安裝後啟用範例服務。

映像版本必須是容器的平台版本加上建置編號，例如 `3.0.0.1`。下一個映像請增加最後的數字。開發板會套用禁止降級原則。

## 5. 建置、簽署並驗證映像

```bash
pib build --sign --supplier 'My Company'
pib verify
```


第一個命令會建立新根檔案系統、安裝應用程式、套用覆蓋層與掛鉤、產生部署成品，並簽署及驗證 SWU。第二個命令示範使用專案預設 CA 與相鄰建置資訊清單的獨立驗證。

## 6. 尋找輸出

開啟專案的 `out/` 目錄：

| 輸出 | 使用方法 |
|---|---|
| `*.swu` | 執行中開發板的已簽署軟體更新 |
| `*.img.gz` | 初始佈建或復原的完整磁碟映像 |
| `*.manifest.json` | 已安裝套件版本、來源與建置識別資訊 |
| `*.cdx.json` | 軟體物料清單 |
| `SHA256SUMS` | 成品校驗碼 |

SWU 與完整磁碟映像是不同部署格式。SWU 安裝與初始 CA 信任設定請遵循[開發板更新參考](palette-image-builder-reference.md#installing-an-swu)。完整磁碟映像請使用 Modalix 佈建程序。正式環境使用前，先在開發板驗證映像。

## 7. 檢查範例行為

套件會安裝 `/usr/bin/pib-example-app`。覆蓋目錄提供設定與 `pib-example.service`。安裝後掛鉤會為 `multi-user.target` 啟用服務，並在映像中寫入 `/etc/pib-example-build`。

依照[板卡更新參考](palette-image-builder-reference.md#installing-an-swu)將映像安裝到開發板後，請**在板卡上**執行：

```bash
sudo systemctl status pib-example.service --no-pager
sudo journalctl -u pib-example.service --no-pager
cat /etc/pib-example-build
```


此服務是單次執行應用程式，成功後即使程序結束仍維持 active 狀態。日誌會包含 `Hello from the custom PIB image.` 與 `/etc/pib-example.conf` 的內容。建置標記內容為 `PIB example post-install hook`。

CI 會在兩種建置器架構上檢查套件檔案、設定、服務啟用、建置標記與已簽署的 SWU 內容。以上板卡檢查可進一步確認實際硬體上的啟動行為。
