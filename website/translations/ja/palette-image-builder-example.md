# カスタムイメージのサンプルをビルドする

この手順では、小さなアプリケーション、設定ファイル、自動起動するサービスを含む署名済み Modalix イメージを作成します。完全なサンプルが PIB に含まれるため、リポジトリの取得やホストへのビルドツールのインストールは不要です。CI でも同じイメージ定義を x86 と ARM64 で検証しています。

## 1. PIB をインストールして確認する

sima-cli をインストールし、Linux エンジンの Docker を起動してから実行します。

```bash
sima-cli neat install sdk/pib
pib --version
pib doctor
```


現在のターミナルで `pib` が見つからない場合は、新しいターミナルを開きます。Bash または Zsh では PATH をすぐに更新することもできます。

```bash
export PATH="$HOME/.local/bin:$PATH"
```


PIB はホストに対応した x86 または ARM64 コンテナを使用します。x86 では ARM64 エミュレーターを自動設定します。この minimal イメージの例には、特権コンテナの許可と、プロジェクトおよび Docker ストレージそれぞれに 10 GiB 以上の空き容量が必要です。

Windows では Linux コンテナモードの Docker とネイティブランチャーを使用します。Windows のインストーラーユニットテストは合格していますが、Docker Desktop/WSL2 での完全なイメージ作成はまだ検証されていません。以下の例は Bash の引用符構文を使用します。

## 2. サンプルをプロジェクトにコピーする

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

## 3. 開発用の署名情報を作成する

```bash
pib keys init --cn 'My Company Development'
```


CA、SWU 署名用の証明書と秘密鍵、カスタム Debian パッケージの署名情報が作成されます。設定後は `keys/ca.key` をプロジェクト外の安全な場所に移動してください。既存ボードを更新する際も同じ CA を維持します。出荷用イメージには組織の本番署名プロセスを使用してください。

## 4. アプリケーションをパッケージ化して署名する

PIB 内でパッケージを作成し、署名と検証を行います。

```bash
pib shell -c 'dpkg-deb --root-owner-group --build package-root custom-debs/pib-example-app_1.0.0_all.deb'
pib sign-debs
pib verify-debs
```


サンプルはシェルスクリプトなのでアーキテクチャは `all` です。コンパイル済みの Modalix アプリケーションは、通常 SDK を使って `arm64` 向けにビルドします。PIB が受け付けるのは ARM64 またはアーキテクチャ非依存のパッケージです。アプリケーションのソースコード自体をクロスコンパイルするツールではありません。

## 5. イメージ定義を確認する

サンプルには次のカスタマイズ設定が含まれます。

```yaml
packages:
  add: [pib-example-app]
  remove: []
overlay: overlay
hooks: [hooks/enable-example.sh]
```


一覧には `.deb` ファイル名ではなく Debian パッケージ名を指定します。`overlay/etc/pib-example.conf` をエディターで変更して独自設定を試してください。フックはパッケージのインストール後にサンプルサービスを有効化します。

イメージのバージョンは、コンテナのプラットフォームリリースにビルド番号を追加した形式（例：`3.0.0.1`）にする必要があります。次回のイメージでは最後の番号を増やします。ボードはダウングレード禁止ポリシーを適用します。

## 6. イメージをビルド・署名・検証する

```bash
pib build --sign --supplier 'My Company'
pib verify
```


最初のコマンドは新しいルートファイルシステムを構築し、アプリケーション、オーバーレイ、フックを適用してデプロイ成果物を作成し、SWU に署名して検証します。2 番目のコマンドは、プロジェクトの既定 CA と隣接するマニフェストによる個別検証を示します。

## 7. 出力を確認する

プロジェクトの `out/` ディレクトリを開きます。

| 出力 | 用途 |
|---|---|
| `*.swu` | 稼働中のボード向けの署名済みソフトウェア更新 |
| `*.img.gz` | 初期プロビジョニングや復旧用の完全なディスクイメージ |
| `*.manifest.json` | インストール済みパッケージのバージョン、取得元、ビルド識別情報 |
| `*.cdx.json` | ソフトウェア部品表 |
| `SHA256SUMS` | 成果物のチェックサム |

SWU とディスクイメージは異なるデプロイ形式です。SWU のインストールと初回 CA 信頼設定は、[ボード更新リファレンス](palette-image-builder-reference.md#installing-an-swu)に従ってください。完全なディスクイメージには Modalix のプロビジョニング手順を使用します。本番環境の前に開発用ボードでイメージを検証してください。

## 8. 独自のアプリケーションに置き換える

SDK で ARM64 Debian パッケージを作成して `custom-debs/` に置き、`image.yaml` にそのパッケージ名を追加します。設定、サービス、フックを変更し、パッケージの署名とイメージ生成を繰り返します。SDK、PIB、DevKit の役割は [SDK アーキテクチャガイド](sdk-architecture.md)を参照してください。

## 繰り返しビルドを高速化する

PIB は pigz で gzip 互換の並列圧縮を行います。検証済みのパッケージダウンロードを再利用するには、次のように設定します。

```bash
export PIB_DEB_CACHE="$HOME/.cache/sima/pib-debs"
pib build --sign
```


リポジトリの署名とパッケージのハッシュは毎回確認されます。キャッシュが温まっていても、ルートファイルシステムの再利用や、インストール、フック、署名、検証の省略は行いません。
