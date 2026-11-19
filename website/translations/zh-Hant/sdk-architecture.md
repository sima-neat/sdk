# Palette SDK 系統堆疊

Palette SDK 提供 Modalix 軟體開發工具。Palette Image Builder（PIB）將軟體組合成自訂 eLxr 作業系統映像。兩者是獨立容器：Palette SDK 工具鏈用於準備目標軟體，PIB 用於組合裝置映像。本指南供處理映像封裝與底層軟體堆疊的系統工程師使用。應用程式 API 與開發流程請前往 [developer.sima.ai/software](https://developer.sima.ai/software)。

SDK 設定也會依相容性目錄安裝版本相容的 **Model Compiler 擴充功能**；若不需要，可略過。擴充功能負責編譯模型產物，SDK 工具鏈負責建置使用模型的應用程式，PIB 再將可部署軟體打包為系統映像。

[![Palette SDK 系統堆疊：開發工具與 Model Compiler 擴充功能產生軟體，再由獨立的 PIB 建立 Modalix DevKit 映像。](../images/palette-sdk-system-stack.svg#gh-light-mode-only)](../images/palette-sdk-system-stack.svg)

[![Palette SDK 系統堆疊：開發工具與 Model Compiler 擴充功能產生軟體，再由獨立的 PIB 建立 Modalix DevKit 映像。](../images/palette-sdk-system-stack-dark.svg#gh-dark-mode-only)](../images/palette-sdk-system-stack-dark.svg)

## 各元件的執行位置

| 元件 | 執行位置 | 職責 |
|---|---|---|
| sima-cli | 您的電腦 | 安裝套件並啟動或設定開發環境 |
| Palette SDK 容器 | 電腦上的 Docker | 以 ARM64 sysroot 進行交叉編譯並提供開發工具 |
| Model Compiler 擴充功能 | 於 SDK 設定期間安裝的開發環境 | 編譯供 Modalix 加速使用的模型 |
| PIB 容器 | 電腦上的 Docker | 依映像規格建立根檔案系統、套件、磁碟映像與已簽署 SWU |
| Modalix DevKit | 目標裝置 | 執行 ARM64 應用程式與已安裝的 eLxr 映像 |

SDK 與 PIB 均有原生 x86 與 ARM64 容器。Docker 會選取適合主機的版本。目標應用程式與裝置映像仍是 ARM64。在 x86 主機組合映像時，PIB 會自動使用 ARM64 模擬。

## 開啟 SDK 開發環境

安裝 Palette SDK 並設定系統軟體開發環境：

```bash
sima-cli neat install sdk
sima-cli sdk setup
sima-cli sdk neat
```


若要在設定時配對 DevKit，請提供位址：

```bash
sima-cli sdk setup --devkit 192.0.2.10
```


將範例位址換成實際 DevKit 位址。建置軟體不一定要配對，但配對有助於硬體部署與測試。

SDK 包含交叉工具鏈、目標 sysroot、標頭檔、程式庫與開發輔助工具。工作區會掛載到容器的 `/workspace`，可在電腦編輯檔案並在 SDK 中建置。

## 軟體如何部署至裝置

使用 SDK 工具鏈，針對 Modalix ARM64 sysroot 建置應用程式。Model Compiler 擴充功能會產生應用程式使用的編譯模型產物。將應用程式、模型資源與必要檔案打包為架構 `arm64` 的 Debian 套件；架構無關的指令碼可使用 `all`。

PIB 將套件、映像規格、設定覆蓋檔案、掛鉤與簽署身分作為輸入，產生更新用的已簽署 `.swu`，以及初始佈建或復原用的 `.img.gz`。只建置應用程式容器不會產生這些系統映像。PIB 可獨立於 SDK 容器運作。

整體流程請參閱[自訂映像工作流程](palette-image-builder.md)，完整範例步驟請參閱[範例映像](palette-image-builder-example.md)。

## 維持工具鏈、映像與開發板版本一致

容器的平台版本決定相容的映像輸入。PIB 會拒絕不同平台版本的專案。映像版本增加數字建置編號，例如 `3.0.0.1`，並用於更新原則。

每個版本均應保留建置資訊清單、SBOM、校驗碼與簽署身分，用以識別出貨內容，並讓後續更新維持在相同受信任 CA 下。發佈的建置容器不內含簽署金鑰。

## 選擇下一步

- 建立第一個映像，請參閱 [自訂映像工作流程](palette-image-builder.md)。
- 建置可執行的應用程式範例，請參閱[範例教學](palette-image-builder-example.md)。
- 自訂核心、外部簽署與開發板更新，請參閱 [PIB 參考](palette-image-builder-reference.md)。
