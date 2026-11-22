# イメージの例

この手順では、小さなアプリケーション、設定ファイル、自動起動するサービスを含む署名済み Modalix イメージを作成します。完全なサンプルが PIB に含まれるため、リポジトリの取得やホストへのビルドツールのインストールは不要です。CI でも同じイメージ定義を x86 と ARM64 で検証しています。

開始前に[カスタムイメージの作成フロー](palette-image-builder.md#install-pib)に従って PIB をインストールしてください。このページでは、同梱の例に固有のファイルとコマンドを説明します。

## 1. サンプルをプロジェクトにコピーする

```bash
pib init my-custom-image --example custom-image
cd my-custom-image
```


主に次のファイルをカスタマイズします。

| ファイル | 用途 |
|---|---|
| `image.yaml` | フレーバー、イメージバージョン、パッケージ、オーバーレイ、フック、署名設定 |
| `package-root/usr/bin/pib-example-app` | サンプル Debian パッケージでインストールするアプリケーション |
| `package-root/DEBIAN/control` | パッケージ名、バージョン、アーキテクチャ |
| `overlay/etc/pib-example.conf` | イメージにコピーするアプリケーション設定 |
| `overlay/etc/systemd/system/pib-example.service` | サービス定義 |
| `hooks/enable-example.sh` | サービスを有効化し、ビルドマーカーを書き込むフック |

コンテナ内の Linux シェルを開くには、次を実行します。

```bash
pib shell
```


プロジェクトは `/workspace` にマウントされます。`exit` でホストに戻ります。以降はホストのプロジェクトディレクトリで操作してください。各 `pib` コマンドがコンテナを自動起動します。

## 2. 開発用の署名情報を作成する

```bash
pib keys init --cn 'My Company Development'
```


CA、SWU 署名用の証明書と秘密鍵、カスタム Debian パッケージの署名情報が作成されます。設定後は `keys/ca.key` をプロジェクト外の安全な場所に移動してください。既存ボードを更新する際も同じ CA を維持します。出荷用イメージには組織の本番署名プロセスを使用してください。

## 3. アプリケーションをパッケージ化して署名する

PIB 内でパッケージを作成し、署名と検証を行います。

```bash
pib shell -c 'dpkg-deb --root-owner-group --build package-root custom-debs/pib-example-app_1.0.0_all.deb'
pib sign-debs
pib verify-debs
```


サンプルはシェルスクリプトなのでアーキテクチャは `all` です。コンパイル済みの Modalix アプリケーションは、通常 SDK を使って `arm64` 向けにビルドします。PIB が受け付けるのは ARM64 またはアーキテクチャ非依存のパッケージです。アプリケーションのソースコード自体をクロスコンパイルするツールではありません。

## 4. イメージ定義を確認する

サンプルには次のカスタマイズ設定が含まれます。

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


一覧には `.deb` ファイル名ではなく Debian パッケージ名を指定します。`overlay/etc/pib-example.conf` をエディターで変更して独自設定を試してください。フックはパッケージのインストール後にサンプルサービスを有効化します。

イメージのバージョンは、コンテナのプラットフォームリリースにビルド番号を追加した形式（例：`3.0.0.1`）にする必要があります。次回のイメージでは最後の番号を増やします。ボードはダウングレード禁止ポリシーを適用します。

## 5. イメージをビルド・署名・検証する

ビルド前に[ボードのログインを設定する](palette-image-builder.md#4-configure-board-login)を完了してください。UART／コンソールのパスワードログインには、このシェルで `PIB_CREDENTIALS` を設定します。未設定の新規イメージでは両パスワードがロックされます。署名情報の生成ではログインパスワードは設定されません。

```bash
pib build --sign --supplier 'My Company'
pib verify
```


最初のコマンドは新しいルートファイルシステムを構築し、アプリケーション、オーバーレイ、フックを適用してデプロイ成果物を作成し、SWU に署名して検証します。2 番目のコマンドは、プロジェクトの既定 CA と隣接するマニフェストによる個別検証を示します。

## 6. 出力を確認する

プロジェクトの `out/` ディレクトリを開きます。

| 出力 | 用途 |
|---|---|
| `*.swu` | 稼働中のボード向けの署名済みソフトウェア更新 |
| `*.img.gz` | 初期プロビジョニングや復旧用の完全なディスクイメージ |
| `*.manifest.json` | インストール済みパッケージのバージョン、取得元、ビルド識別情報 |
| `*.cdx.json` | ソフトウェア部品表 |
| `SHA256SUMS` | 成果物のチェックサム |

SWU とディスクイメージは異なるデプロイ形式です。SWU のインストールと初回 CA 信頼設定は、[ボード更新リファレンス](palette-image-builder-reference.md#installing-an-swu)に従ってください。完全なディスクイメージには Modalix のプロビジョニング手順を使用します。本番環境の前に開発用ボードでイメージを検証してください。

## 7. 例の動作を確認する

パッケージは `/usr/bin/pib-example-app` をインストールします。オーバーレイは設定ファイルと `pib-example.service` を提供します。インストール後フックは `multi-user.target` でサービスを有効にし、イメージ内に `/etc/pib-example-build` を書き込みます。

[ボード更新リファレンス](palette-image-builder-reference.md#installing-an-swu)に従って開発用ボードにイメージをインストールした後、次のコマンドを**ボード上で**実行します。

```bash
sudo systemctl status pib-example.service --no-pager
sudo journalctl -u pib-example.service --no-pager
cat /etc/pib-example-build
```


サービスは一度だけ実行されるアプリケーションです。成功するとプロセス終了後も active 状態を維持します。ジャーナルには `Hello from the custom PIB image.` と `/etc/pib-example.conf` の内容が記録されます。ビルドマーカーは `PIB example post-install hook` です。

CI は両方のビルダーアーキテクチャで、パッケージファイル、設定、サービス有効化、ビルドマーカー、署名済み SWU のペイロードを検証します。上記のボード上の確認では、実際のハードウェアでの起動動作も検証できます。
