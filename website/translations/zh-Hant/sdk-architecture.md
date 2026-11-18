# 了解 Palette SDK 系統堆疊

Palette SDK 提供 Modalix 軟體開發工具。Palette Image Builder（PIB）將軟體組合成自訂 eLxr 作業系統映像。兩者是獨立容器：Palette SDK 工具鏈用於準備目標軟體，PIB 用於組合裝置映像。本指南供處理映像封裝與底層軟體堆疊的系統工程師使用。應用程式 API 與開發流程請前往 [developer.sima.ai/software](https://developer.sima.ai/software)。

## 各元件的執行位置

| 元件 | 執行位置 | 職責 |
|---|---|---|
| sima-cli | 您的電腦 | 安裝套件並啟動或設定開發環境 |
| Palette SDK 容器 | 電腦上的 Docker | 以 ARM64 sysroot 進行交叉編譯並提供開發工具 |
| PIB 容器 | 電腦上的 Docker | 依映像規格建立根檔案系統、套件、磁碟映像與已簽署 SWU |
| Modalix DevKit | 目標裝置 | 執行 ARM64 應用程式與已安裝的 eLxr 映像 |

SDK 與 PIB 均有原生 x86 與 ARM64 容器。Docker 會選取適合主機的版本。目標應用程式與裝置映像仍是 ARM64。在 x86 主機組合映像時，PIB 會自動使用 ARM64 模擬。

## 開啟系統軟體工具鏈

安裝 Palette SDK 並設定系統軟體開發環境：

```bash
sima-cli neat install sdk@develop
sima-cli sdk setup
sima-cli sdk neat
```


若要在設定時配對 DevKit，請提供位址：

```bash
sima-cli sdk setup --devkit 192.0.2.10
```


將範例位址換成實際 DevKit 位址。建置軟體不一定要配對，但配對有助於硬體部署與測試。

SDK 包含交叉工具鏈、目標 sysroot、標頭檔、程式庫與開發輔助工具。工作區會掛載到容器的 `/workspace`，可在電腦編輯檔案並在 SDK 中建置。

## 將結果封裝到映像

以 Modalix ARM64 sysroot 建置，將應用程式與必要檔案封裝成架構為 `arm64` 的 Debian 套件。指令碼等與架構無關的內容可使用 `all`。

應用程式容器與裝置作業系統映像用途不同。建置應用程式 Docker 映像不會產生 SWU，也不會取代開發板的 eLxr 根檔案系統。

## 透過 PIB 組合裝置映像

獨立安裝 PIB：

```bash
sima-cli neat install sdk/pib
pib doctor
pib init my-image --flavor minimal
cd my-image
```


專案結合下列項目：

- `image.yaml`：選取映像類型、版本、套件與簽署身分。
- `custom-debs/`：已簽署的 ARM64 或與架構無關套件。
- `overlay/`：設定與要加入映像的 root 所有檔案。
- `hooks/`：套件安裝完成後的變更。
- `keys/`：簽署身分與公開信任資料。

PIB 從設定的儲存庫下載套件並建立新根檔案系統，產生更新用的已簽署 `.swu` 與完整磁碟佈建／復原用的 `.img.gz`。不需要啟動主要 SDK 容器。

從[完整自訂映像範例](palette-image-builder-example.md)開始，了解應用程式封裝、服務與安裝後掛鉤如何一起使用。

## 維持工具鏈、映像與開發板版本一致

容器的平台版本決定相容的映像輸入。PIB 會拒絕不同平台版本的專案。映像版本增加數字建置編號，例如 `3.0.0.1`，並用於更新原則。

每個版本均應保留建置資訊清單、SBOM、校驗碼與簽署身分，用以識別出貨內容，並讓後續更新維持在相同受信任 CA 下。發佈的建置容器不內含簽署金鑰。

## 選擇下一步

- 建立第一個映像，請參閱 [PIB 入門指南](palette-image-builder.md)。
- 建置可執行的應用程式範例，請參閱[範例教學](palette-image-builder-example.md)。
- 自訂核心、外部簽署與開發板更新，請參閱 [PIB 參考](palette-image-builder-reference.md)。
