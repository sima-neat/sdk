# カスタムイメージの作成フロー

Palette SDK の補完ツールである Palette Image Builder（PIB）を使って、ソフトウェアとシステム設定から Modalix 用のカスタム eLxr イメージを作成します。このページは全体の流れを説明します。パッケージ、サービス、オーバーレイを実際に作る手順は[イメージの例](palette-image-builder-example.md)をご覧ください。

## PIB をインストールする

[sima-cli](https://docs.sima-neat.com/getting-started/installation) をインストールし、Linux エンジンの Docker を起動してから実行します。

```bash
sima-cli neat install sdk/pib
```


インストーラーはホストに対応する x86_64 または ARM64 コンテナを選び、ランチャーと PATH を設定し、Docker ホストを自動チェックします。PATH が更新された場合は新しいターミナルを開いてください。PIB の実行にメインの SDK コンテナは不要です。

イメージ作成には Docker の特権アクセス、リポジトリへの接続、およびプロジェクトと Docker ストレージの両方に空き容量が必要です。`minimal` は 10 GiB、`palette` は 20 GiB を目安にしてください。x86 では ARM64 エミュレーションを自動設定します。対応プラットフォーム、別リリースの選択、手動インストールについては[インストールのリファレンス](palette-image-builder-reference.md#installation)を参照してください。

## 1. イメージプロジェクトを作成する

```bash
pib init my-image --flavor minimal
cd my-image
```


プラットフォームのリリースに対応するフレーバーを選びます。デスクトップとより多くのパッケージが必要なら `palette` を使用します。`configs/` のボード既定値は選択したビルダーが提供するため、通常は変更しません。以降のコマンドはプロジェクトディレクトリで実行します。

## 2. イメージの内容を定義する

| 入力 | 用途 |
|---|---|
| `image.yaml` | フレーバー、リリース、イメージバージョン、パッケージ、署名設定 |
| `custom-debs/` | ARM64 またはアーキテクチャ非依存の Debian パッケージ |
| `overlay/` | ルートファイルシステムにコピーする設定などのファイル |
| `hooks/` | サービス有効化など、パッケージインストール後の処理 |

Palette SDK でアプリケーションをビルドし、モデルをコンパイルした後、ターゲットに必要なファイルをパッケージ化します。PIB はパッケージを組み立てるツールであり、アプリケーションソースはコンパイルしません。各コンポーネントの役割は [Palette SDK システムスタック](sdk-architecture.md)をご覧ください。ただし、カーネルは例外です。`pib sbp` が SiMa の公開ソースまたは独自のソースからカーネルをビルドし、カーネルパッケージとして `custom-debs/` に出力します。[カーネルのビルド](palette-image-builder-reference.md#building-the-kernel)を参照してください。

`image.yaml` には `.deb` ファイル名ではなく Debian パッケージ名を指定します。ファイルにはオーバーレイ、インストール後の変更にはフックを使います。パッケージ、カーネル、フックの詳細な規則は[カスタマイズのリファレンス](palette-image-builder-reference.md#customization)にあります。

## 3. 署名と信頼を準備する

開発用の署名情報をプロジェクトごとに一度作成します。

```bash
pib keys init --cn 'My Company Development'
```


設定後は CA 秘密鍵をオフラインで保管します。既存ボードの更新には同じ CA を維持し、出荷用イメージには組織の本番署名プロセスを使用してください。外部鍵、更新、ビルドと署名の分離については[署名のリファレンス](palette-image-builder-reference.md#signing)を参照してください。

## 4. ボードのログインを設定する

**UART／コンソールのパスワードログインには、ビルド前に `PIB_CREDENTIALS` を設定してください。** 署名鍵の生成ではログインパスワードは設定されません。このファイルがなければ、新規イメージの `root` と `sima` のパスワードはロックされ、SSH 鍵で接続できてもコンソールのパスワードログインは失敗します。

プロジェクト内から、ホストの OpenSSL でパスワードハッシュを含む保護されたファイルを作ります。最初に `root`、次に `sima` のパスワードを入力して確認します。

```bash
mkdir -p ../secure
chmod 700 ../secure
(umask 077; printf 'root:%s\nsima:%s\n' \
  "$(openssl passwd -6)" "$(openssl passwd -6)" > ../secure/credentials)
chmod 600 ../secure/credentials
export PIB_CREDENTIALS="$(cd ../secure && pwd)/credentials"
```

ファイルはプロジェクトとソース管理の外に保管してください。同じシェルでビルドします。新しいシェルでは `PIB_CREDENTIALS` を再度 export してください。PIB はビルド時にファイルを読み取り専用でマウントします。

SSH 鍵のみを使う場合は、認証ファイルを省略してビルド前に許可済み公開鍵を追加できます。[ボードへのアクセス](palette-image-builder-reference.md#board-access)を参照してください。root パスワードを設定しても root SSH は鍵認証のみです。更新した既存ボードでは、永続オーバーレイに以前の認証情報が残る場合があります。

## 5. ビルドして検証する

独自 Debian パッケージを使用する場合は、イメージ作成前に署名と検証を行います。

```bash
pib sign-debs
pib verify-debs
pib build --sign
pib verify
```


ビルドは新しいルートファイルシステムを作成し、プロジェクトの入力を適用し、デプロイ用成果物を生成して SWU を署名・検証します。成果物、パッケージマニフェスト、SBOM、チェックサムは `out/` に出力されます。

## 6. デプロイして保守する

| 成果物 | デプロイ用途 |
|---|---|
| 署名済み `.swu` | 稼働中のボードの更新 |
| `.img.gz` | ディスクの初期プロビジョニングや復旧 |

デプロイ前にボードへのアクセスと CA の信頼を設定します。[ボードへのアクセス](palette-image-builder-reference.md#board-access)と [SWU のインストール](palette-image-builder-reference.md#installing-an-swu)に従ってください。ビルド成功だけではボードの変更や動作確認は行われません。

復旧可能なハードウェアでイメージを検証し、マニフェスト、チェックサム、署名情報を保管してください。更新時はイメージバージョンを増やし、プラットフォームを変更する場合は新しいプロジェクトに互換性のある入力を移行します。[プラットフォーム更新のリファレンス](palette-image-builder-reference.md#new-platform-release)も参照してください。

ブートパーティション、rootfs スロット、データ容量の割り当ては[メディアとパーティション構成](palette-image-builder-reference.md#media-and-partition-layout)を参照してください。

## 例またはリファレンスへ進む

- [イメージの例](palette-image-builder-example.md)：同梱のアプリケーションパッケージ、設定、サービスを手順に沿って作成します。
- [Palette Image Builder リファレンス](palette-image-builder-reference.md)：コマンド、カスタマイズ規則、署名、トラブルシューティング、ボード操作。
