# Palette SDK システムスタック

Palette SDK は Modalix 向けソフトウェアの開発ツールを提供します。Palette Image Builder（PIB）は、そのソフトウェアをカスタム eLxr OS イメージに組み込みます。独立したコンテナなので、アプリケーション開発には SDK、デバイスイメージのカスタマイズには PIB を使用します。

このガイドは、イメージのパッケージ化と低レベルソフトウェアを扱うシステムエンジニア向けです。アプリケーション API と開発手順は [developer.sima.ai/software](https://developer.sima.ai/software) を参照してください。

SDK のセットアップは互換性カタログから対応する **Model Compiler 拡張機能**もインストールします。不要な場合はスキップできます。拡張機能はモデルをコンパイルし、SDK ツールチェーンはそれを使用するアプリケーションをビルドします。PIB はデプロイするソフトウェアをシステムイメージにまとめます。

[![Palette SDK のシステムスタック：開発ツールと Model Compiler 拡張機能が生成したソフトウェアを、独立した PIB が Modalix DevKit 用イメージにまとめます。](../images/palette-sdk-system-stack.svg#gh-light-mode-only)](../images/palette-sdk-system-stack.svg)

[![Palette SDK のシステムスタック：開発ツールと Model Compiler 拡張機能が生成したソフトウェアを、独立した PIB が Modalix DevKit 用イメージにまとめます。](../images/palette-sdk-system-stack-dark.svg#gh-dark-mode-only)](../images/palette-sdk-system-stack-dark.svg)

## 各コンポーネントの実行場所

| コンポーネント | 実行場所 | 役割 |
|---|---|---|
| sima-cli | ホストコンピューター | パッケージをインストールし、開発環境を起動・設定する |
| Palette SDK コンテナ | ホストの Docker | ARM64 sysroot に対してアプリケーションをクロスコンパイルし、開発ツールを提供する |
| Model Compiler 拡張機能 | SDK セットアップでインストールされる開発環境 | Modalix アクセラレーション向けにモデルをコンパイル |
| PIB コンテナ | ホストの Docker | イメージ定義からルートファイルシステム、パッケージ、ディスクイメージ、署名済み SWU を作成する |
| Modalix DevKit | ターゲットデバイス | ARM64 アプリケーションとインストール済み eLxr イメージを実行する |

SDK と PIB の両方に、x86 と ARM64 のネイティブコンテナがあります。Docker がホストに合うものを選択します。ターゲットのアプリケーションとデバイスイメージは ARM64 のままです。x86 ホストでイメージを作成するとき、PIB は ARM64 エミュレーションを自動的に使用します。

## SDK の開発環境を開く

SDK をインストールし、開発環境を設定します。

```bash
sima-cli neat install sdk
sima-cli sdk setup
sima-cli sdk neat
```


セットアップ時に DevKit と接続するには、そのアドレスを指定します。

```bash
sima-cli sdk setup --devkit 192.0.2.10
```


例のアドレスを DevKit の実際のアドレスに置き換えてください。ソフトウェアのビルドに接続設定は必須ではありませんが、ハードウェアへのデプロイやテストに役立ちます。

SDK には、クロスツールチェーン、ターゲット sysroot、ヘッダー、ライブラリ、開発ヘルパーが含まれます。ワークスペースはコンテナの `/workspace` にマウントされるため、ホストで編集して SDK 内でビルドできます。

## ソフトウェアがデバイスに届くまで

SDK のツールチェーンで Modalix の ARM64 sysroot に対してアプリケーションをビルドします。Model Compiler 拡張機能は、アプリケーションが使用するモデルのコンパイル済み成果物を生成します。アプリケーション、モデル、必要なファイルをアーキテクチャ `arm64` の Debian パッケージにします。アーキテクチャ非依存のスクリプトは `all` を使用できます。

PIB はパッケージ、イメージ仕様、設定オーバーレイ、フック、署名情報を入力として、更新用の署名済み `.swu` と初期プロビジョニング・復旧用の `.img.gz` を作成します。アプリケーションコンテナのビルドだけでは、これらのシステムイメージ成果物は生成されません。PIB は SDK コンテナとは独立して実行できます。

全体の流れは[カスタムイメージの作成フロー](palette-image-builder.md)、完全なサンプル手順は[イメージの例](palette-image-builder-example.md)をご覧ください。

## ツールチェーン・イメージ・ボードのバージョンを合わせる

コンテナのプラットフォームリリースにより、互換性のあるイメージ入力が決まります。PIB は別のリリース向けのプロジェクトを拒否します。イメージバージョンは `3.0.0.1` のような数値のビルド番号を追加し、更新ポリシーに使用されます。

各リリースのビルドマニフェスト、SBOM、チェックサム、署名情報を保存してください。出荷した内容を識別し、同じ信頼済み CA のもとで更新を続けるために必要です。公開されるビルダーコンテナに署名鍵は含まれません。

## 次のステップを選ぶ

- 初めてのイメージ作成は [カスタムイメージの作成フロー](palette-image-builder.md)を参照してください。
- 動作するアプリケーション例は [サンプルの手順](palette-image-builder-example.md)を参照してください。
- カスタムカーネル、外部署名、ボード更新は [PIB リファレンス](palette-image-builder-reference.md)を参照してください。
