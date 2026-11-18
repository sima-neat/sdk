# カスタム Modalix イメージを作成する

Palette Image Builder（PIB）は、Modalix 向けのカスタム eLxr イメージを作成します。Palette SDK リポジトリで管理される独立した Docker コンテナとして提供されます。sima-cli でインストールでき、メインの SDK コンテナは不要です。

1 つのプロジェクトから、2 種類のデプロイ形式を生成できます。

- **`.swu`**：稼働中のボードに適用する署名済み更新バンドル。
- **`.img.gz`**：初期プロビジョニングや復旧用のディスクイメージ。

## 1. PIB をインストールする

[sima-cli](https://docs.sima-neat.com/getting-started/installation) と Docker をインストールしてから、次を実行します。

```bash
sima-cli neat install sdk/pib
pib doctor
```


インストーラーは x86_64 または ARM64 用のコンテナをダウンロードし、Linux、macOS、Windows に `pib` コマンドをインストールします。PATH が更新された場合は、新しいターミナルを開いてください。PIB は Linux コンテナで動作します。Docker を起動し、イメージ作成に必要な特権アクセスを許可してください。x86 の Docker ホストでは、同梱の ARM64 エミュレーターが自動設定されます。

ローカルのプロジェクトフォルダーには `minimal` で 10 GiB 以上、`palette` で 20 GiB 以上の空き容量を確保し、Docker ストレージにも同程度の空き容量を用意してください。ビルドには Debian/eLxr と SiMa のパッケージリポジトリへの接続が必要です。生成されるボードイメージは ARM64 です。

`sdk/pib` は main で最後に公開されたパッケージを選択します。別の SDK ブランチやリリースを選ぶ場合は、SDK と同じ構文を使います。例：`sima-cli neat install sdk/pib@develop`。Docker による手動インストールやホストの詳細は、[インストールのリファレンス](palette-image-builder-reference.md#installation)を参照してください。

## 2. イメージプロジェクトを作成する

```bash
pib init my-image --flavor minimal
cd my-image
```


デスクトップとより多くのパッケージが必要な場合は `--flavor palette` を使用します。プラットフォームのリリースは、選択したコンテナによって決まります。プロジェクトには次のファイルとディレクトリが含まれます。

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


以降のコマンドは、このプロジェクトディレクトリから実行します。プロジェクトをマウントしたシェルを開くには `pib shell` を実行します。シェル内では `pib` を直接実行し、`exit` でホストに戻ります。

アプリケーションパッケージ、設定オーバーレイ、サービス有効化フックを含む動作例には、代わりに `pib init my-image --example custom-image` を使用します。[サンプルの手順](palette-image-builder-example.md)で一連の操作を説明しています。CI でも、リポジトリにある同じ `image.yaml` を両アーキテクチャでビルドします。サンプルはコンテナに含まれるため、リポジトリの取得は不要です。

## 3. 署名を初回設定する

開発用にテスト CA と署名用の識別情報を作成します。

```bash
pib keys init --cn 'My Company Development'
```


設定後は `keys/ca.key` を安全なオフラインの場所に移動してください。署名用のリーフ証明書と秘密鍵は `keys/` に残ります。生成される `.gitignore` は秘密鍵とビルド出力を除外します。署名情報を安全にバックアップしてください。既存のボードはこの CA を信頼するため、新しいプロジェクトやプラットフォームリリースに移行する際も同じ CA を維持します。

本番環境では、組織の署名用識別情報を使用します。[外部の鍵と証明書の更新](palette-image-builder-reference.md#signing)を参照してください。コンテナに SiMa の本番用署名鍵は含まれません。

## 4. イメージをカスタマイズする

最初のビルドでは、エディターで `overlay/etc/motd` を作成します。

```text
My custom Modalix image
```


`overlay/` のファイルは権限を保持し、イメージ内では root 所有になります。オーバーレイはパッケージのインストール前に適用されるため、`/etc` 以外のファイルはパッケージによって置き換えられる場合があります。インストール後に必要な変更にはフックを使用してください。

アプリケーションを Debian パッケージとして追加するには、次を実行します。

```bash
cp /path/to/my-app_1.0_arm64.deb custom-debs/
pib sign-debs
pib verify-debs
```


ファイル名ではなく、**パッケージ名**を `image.yaml` に追加します。

```yaml
packages:
  add: [my-app]
  remove: []
```


パッケージの対象アーキテクチャは `arm64` または `all` である必要があります。カーネルの置換、パッケージの削除、サービスの有効化、独自の更新スクリプトについては、[カスタマイズのリファレンス](palette-image-builder-reference.md#customization)を参照してください。

## 5. 署名済み更新をビルドする

```bash
pib build --sign
```


このコマンドはイメージをビルドし、設定した識別情報で SWU に署名して、署名、ペイロードのハッシュ、ビルドマニフェストを検証します。通常はホストとネットワークに応じて数分かかります。結果は `out/` に出力されます。

| 出力 | 用途 |
|---|---|
| `*.swu` | 署名済み更新バンドル |
| `*.unsigned.swu` | 別の署名工程に渡すバンドル |
| `*.img.gz` | プロビジョニング・復旧用の圧縮ディスクイメージ |
| `*-boot0.be` | 対応する tRoot ペイロード |
| `*.manifest.json` | パッケージのバージョン・取得元とブートペイロードの出所 |
| `*.cdx.json` | CycloneDX ソフトウェア部品表 |
| `SHA256SUMS` | 成果物のチェックサム |

ファイル名を探さずに再検証するには、次を実行します。

```bash
pib verify
```


CI や独立した署名システムでは、`pib build`、`pib sign`、`pib verify` を個別に実行できます。`out/` に以前のバージョンがあっても、`pib sign` と `pib verify` は現在の `image.yaml` のバージョンを選択します。

次のビルド前に、`image.yaml` の `version` の最後の数値を増やしてください。例：`3.0.0.1` から `3.0.0.2`。同じバージョンを再ビルドすると、既存の署名済み SWU を含む出力が置き換えられます。ボードではイメージのバージョンポリシーが適用されます。

## 6. デプロイの準備をする

バンドルのビルドと検証だけではボードは変更されません。デプロイ前に次を確認します。

- 新しいボードに書き込む場合は、初回起動時のアクセスを設定します。既定では `root` と `sima` はロックされています。更新では既存の認証情報が保持される場合があります。[ボードへのアクセス](palette-image-builder-reference.md#board-access)を参照してください。
- 認可されたボードプロビジョニング手順で CA を設定します。標準イメージのボードが、新しく作成した CA を自動的に信頼することはありません。
- `.swu` には SWUpdate、`.img.gz` と必要なブートペイロードにはボードで検証されたメディア書き込み・復旧手順を使用します。

SSH での更新コマンドは [SWU のインストール](palette-image-builder-reference.md#installing-an-swu)を参照してください。本番環境で使用する前に、復旧可能な開発用ボードでカスタムイメージを検証してください。

## トラブルシューティング

- **ループデバイスや device-mapper にアクセスできない場合：** `pib doctor` を実行します。ランチャーは必要な特権を付与しますが、Linux Docker ホスト側でデバイスを提供する必要があります。
- **x86 で ARM64 の設定に失敗する場合：** PIB は同梱のエミュレーターを自動登録します。Linux Docker エンジンで特権 binfmt アクセスが許可されているか確認してください。
- **ビルドが中断された場合：** まずビルドを停止し、`pib clean` で残存リソースを確認してから `pib clean --yes` で削除します。同じ Docker ホスト上の別プロジェクトのリソースも対象になる場合があります。
- **パッケージや bootstrap が失敗する場合：** `configs/images/mmdebstrap.log` を確認します。ビルド中はパッケージリポジトリに接続できる必要があります。
- **新しいプラットフォームリリースの場合：** 対応するコンテナで新しいプロジェクトを作成し、既存の CA と互換性のあるパッケージ・カスタマイズを移行します。[アップグレードのリファレンス](palette-image-builder-reference.md#new-platform-release)を参照してください。
