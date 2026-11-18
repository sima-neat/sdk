# 處理底層系統軟體

本指南供準備 Modalix 映像 BSP 軟體的系統工程師使用。透過 Palette SDK 工具鏈處理核心與裝置樹原始碼，再使用 PIB 將與版本相容的套件組合到映像中。應用程式 API 與開發教學請參閱 [developer.sima.ai/software](https://developer.sima.ai/software)。

## 從相容的 BSP 版本開始

使用符合目標平台版本的供應商原始碼修訂版與設定。儲存庫的預設分支不一定是目前維護映像使用的原始碼。請在版本紀錄保存原始碼修訂版、設定變更與套件版本。

下列建置命令在已設定 ARM64 交叉工具鏈環境的 Palette SDK 容器內執行。取得原始碼後，在設定與建置之前先選取適當的版本修訂版。

## 設定並建置核心

```bash
git clone https://github.com/SiMa-ai/simaai-linux.git
cd simaai-linux
make ARCH=arm64 simaai_modalix_defconfig
make all -j8 ARCH=arm64 LOCALVERSION="-modalix" DTC_FLAGS=-@
```


核心映像位於 `arch/arm64/boot/Image`，平台裝置樹位於 `arch/arm64/boot/dts/simaai/`。請記錄所用設定與原始碼修訂版。

這些是建置成品，不是完整的 PIB 相容核心套件。請使用平台支援的 Debian 封裝流程，以保留必要的開機檔案、套件指令碼與版本整合。

## 編譯裝置樹覆蓋層

```bash
dtc -@ -I dts -O dtb -o imx415.dtbo imx415.dtso
```


將範例檔名換成您的覆蓋層。在開發板上驗證硬體繫結與周邊行為，並依平台版本支援的開機設定封裝或安裝。單獨複製 `.dtbo` 不會自動啟用它。

## 了解開機鏈邊界

映像中的核心、U-Boot、ATF 與 tRoot 必須相容。目前 PIB 流程要求自訂核心保留版本原有的核心套件名稱，且必須是唯一安裝的核心。名稱可在 `configs/images/image-params.yaml` 找到。

PIB 會拒絕本機替換 tRoot、ATF 與 U-Boot 的套件。映像中的 U-Boot 必須與 `fip.bin` 內的副本一致。建置 `u-boot.bin` 並不代表取得覆寫開機韌體的授權，也不等於受支援的寫入程序。開機鏈變更須與平台供應商及其復原／簽署流程協調。

`securepalette` 類型增加核心 FIT 簽章檢查，正式出貨需要正式簽署的開機套件。其安全開機硬體行為須另外驗證，不能以 minimal 映像 CI 驗證代替。

## 使用 PIB 封裝系統變更

將符合版本的 ARM64 Debian 套件放在 `custom-debs/`，以套件簽署身分簽署後建置映像：

```bash
pib sign-debs
pib verify-debs
pib build --sign
pib verify
```


`image.yaml` 定義額外套件名稱，`overlay/` 放置設定，安裝後掛鉤負責啟用服務等最終變更。核心與套件規則詳見 [PIB 參考](palette-image-builder-reference.md#customization)。

保留資訊清單與校驗碼，在可復原的開發板測試結果，並驗證受變更影響的周邊與更新／回復行為。成功建置成品並不表示硬體相容性已獲驗證。
