# Palette Image Builder リファレンス

まず [カスタムイメージの作成フロー](palette-image-builder.md)を参照してください。このページは追加機能とボード操作を説明します。コンテナの保守については [ビルダー README](../palette-image-builder/README.md)を参照してください。

## インストール

標準のインストールコマンドは `sima-cli neat install sdk/pib` です。選択した SDK 公開物の `pib/` メタデータから検証済みマルチプラットフォームイメージを取得し、ホストランチャーをインストールします。Python は sima-cli の環境を使用し、ビルドツールはコンテナ内にあります。既定は main で、`sdk/pib@develop` や `sdk/pib@<release>` で別の公開物を選択できます。

Windows では Docker Desktop を Linux コンテナモードにして PowerShell から実行します。インストーラーは `pib.cmd` を作成し、ユーザー PATH を更新します。Linux/macOS では `~/.local/bin` にインストールし、必要に応じてシェルプロファイルを更新します。いずれも amd64/arm64 イメージを自動選択します。Linux Docker ホストはループデバイス、device-mapper、binfmt_misc のカーネル機能を提供する必要があり、デスクトップ VM でも同様です。`pib doctor` で確認します。完全なイメージ作成はネイティブ Linux x86/ARM と Apple Silicon/Colima で検証済みです。Windows のインストーラーテストは、Windows 上の完全なイメージ作成を保証するものではありません。

sima-cli を使わず Docker から手動で使用する場合は、公開イメージを取得してランチャーを取り出します。Python 3 を PATH に用意してください。

```bash
export PIB_IMAGE=ghcr.io/sima-neat/palette-image-builder-develop:latest
docker pull "$PIB_IMAGE"
mkdir -p "$HOME/.local/bin"
docker run --rm --entrypoint cat "$PIB_IMAGE" \
  /usr/local/share/pib/host/pib > "$HOME/.local/bin/pib"
chmod +x "$HOME/.local/bin/pib"
export PATH="$HOME/.local/bin:$PATH"
pib doctor
```


x86 イメージにはエミュレーターが含まれます。特権 PIB の起動時に、動作する ARM64 ハンドラーがなければ Docker ホストの Linux カーネルに登録します。既存の動作するハンドラーは保持され、ネイティブ ARM64 では登録不要です。Docker ホスト再起動後の再登録も自動です。ホストにパッケージをインストールしません。

## 環境変数

ホストで `pib` を実行するシェルに設定します。ファイルは Docker から参照可能にしてください。認証・署名ファイルは使用するコマンドにのみ読み取り専用でマウントします。`PIB_CONFIGS` は親ディレクトリを読み取り専用、`PIB_DEB_CACHE` は書き込み可能でマウントします。

| 変数 | 使用コマンド | 用途 |
|---|---|---|
| `PIB_IMAGE` | 全コマンド | インストール済みコンテナをタグまたはダイジェストで上書き。 |
| `PIB_CREDENTIALS` | `pib build` | `root:<hash>` と `sima:<hash>` のハッシュファイル。未指定の新規イメージは両パスワードをロックします。既存ボードは永続オーバーレイに認証情報を保持する場合があります。 |
| `SWU_SIGNING_KEY`, `SWU_SIGNING_CERT` | `pib sign`, `pib build --sign` | 外部署名鍵と証明書。鍵は `pkcs11:` URI も使用可能。既定はプロジェクト設定で、証明書はイメージの信頼する CA に連鎖する必要があります。 |
| `PIB_CONFIGS` | `pib init` | 上級者向け：同梱設定に代わる外部イメージ設定ディレクトリ。 |
| `PIB_PCSCD_DIR` | 署名コマンド | pcscd ソケットのディレクトリ。既定 `/run/pcscd`。Linux コンテナからアクセス可能なソケットが必要。 |
| `PIB_DEB_CACHE` | `pib build`, `pib shell` | Debian ダウンロードのホストキャッシュ。毎回、認証済みメタデータのハッシュとサイズで検証。 |
| `PIB_KERNEL_URL`, `PIB_KERNEL_REF` | `pib package` | 実行のたびにビルドするカーネルリポジトリ（認証情報を含まない https URL）と、そのブランチまたはコミット。`--kernel-url` と `--kernel-ref` は、1 回の実行に限りこれらを上書きします。 |
| `PIB_KERNEL_SRC` | `pib package` | 独自のカーネルを含むホスト上の Git リポジトリ（チェックアウトまたはベアリポジトリ）。読み取り専用でマウントされます。非公開リポジトリや、どこにもプッシュしていないコミットに使用します。 |
| `PIB_PKGBUILD_SRC` | `pib package` | sbp（`pkgbuild/`）とそのパッケージ設定（`configs/packages/`）を含むチェックアウト。PIB イメージ内のものの代わりに使用されます。マウントされるのはこの 2 つのディレクトリだけで、読み取り専用です。 |
| `PIB_PACKAGE_JOBS`, `PIB_CCACHE_SIZE`, `PIB_PACKAGE_VOLUME` | `pib package` | 並列コンパイルのジョブ数。コンパイラーキャッシュのサイズ（既定 `5G`）。sbp の作業ツリー、パッケージリポジトリ、キャッシュ用の Docker ボリューム（既定 `pib-package-<uid>`）。 |

## コマンド

イメージの圧縮は、ビルダーで利用できる CPU コアを使用する pigz で行います。出力は gzip 互換であり、署名と検証は実際の圧縮ペイロードを対象とします。

ビルド間で Debian のダウンロードを再利用するには、ホストのキャッシュディレクトリを指定します。

```bash
export PIB_DEB_CACHE="$HOME/.cache/sima/pib-debs"
pib build --sign
```


キャッシュするのはパッケージのバイト列のみです。各 bootstrap は最新のリポジトリメタデータを取得して認証し、SHA256 とサイズでキャッシュを検証します。破損したデータは破棄して再取得します。ルートファイルシステム、パッケージのインストール、フック、署名、検証は毎回実行します。カスタムパッケージが含まれる場合があるので、キャッシュは自分のユーザーディレクトリに置いてください。

| コマンド | 用途 |
|---|---|
| `pib doctor` | ツール、空き容量、ループデバイス、device-mapper、エミュレーションの確認 |
| `pib init DIR --flavor minimal` | プロジェクト作成。minimal、palette を選択可能 |
| `pib init DIR --example custom-image` | 完全なサンプル定義と入力のコピー |
| `pib shell` | 現在のプロジェクトをマウントしたコンテナシェルを開く |
| `pib keys init --cn NAME` | CA、SWU リーフ証明書、Debian 署名情報の生成 |
| `pib keys renew --cn NAME` | 同じ CA でリーフ証明書を更新 |
| `pib keys fit` | `pib package` がビルドするカーネル FIT イメージに署名する鍵ペアの生成 |
| `pib package -p linux` | カーネルと palette のカーネルモジュールパッケージをビルドし、`custom-debs/` に出力 |
| `pib sign-debs` / `pib verify-debs` | カスタム Debian パッケージの署名・確認 |
| `pib build [--sign] [--supplier NAME]` | ビルド、および任意の署名・検証 |
| `pib sign [FILE]` | バンドルに署名。既定は現在のプロジェクトバージョン |
| `pib verify [FILE] [--ca CRT] [--manifest JSON]` | 署名とペイロードを検証。プロジェクト設定と隣接マニフェストを自動選択 |
| `pib diff --against MANIFEST` | 以前のビルドとのパッケージ差分 |
| `pib clean [--yes]` | ビルドのループデバイスとボリュームグループの確認・削除 |

すべてのコマンドはコンテナ内で実行されます。ホストランチャーは Docker、ワークスペースのマウント、明示的に指定した外部ファイルだけを扱います。`build`、`doctor`、`clean`、対話シェルは特権デバイスアクセスを使用します。署名、検証、鍵生成、プロジェクト作成には不要です。`pib package` は特権なしで実行され、プロジェクトのうち `custom-debs/` 以外は読み取り専用で参照します。`keys/` のうち参照できるのはカーネル FIT 鍵ペアだけです。

## ビルド成果物

| ファイル | 技術的な用途 |
|---|---|
| `*.swu` | 署名済み更新バンドル |
| `*.unsigned.swu` | 分離した署名処理への入力 |
| `*.img.gz` | プロビジョニング・復旧用の圧縮ディスクイメージ |
| `*-boot0.be` | 関連する tRoot ペイロード。プラットフォームの準備手順に従う |
| `*.manifest.json` | パッケージのバージョン、取得元、ブートデータの来歴 |
| `*.cdx.json` | CycloneDX ソフトウェア部品表 |
| `SHA256SUMS` | 成果物のチェックサム |

`out/` に古い成果物があっても、`pib sign` と `pib verify` は現在の `image.yaml` バージョンを選びます。同じバージョンを再ビルドすると、署名済み SWU を含む出力が置き換わります。次の更新ではバージョンを増やしてください。

## メディアとパーティション構成

Modalix の eMMC/SD イメージは GPT のブートパーティションと、ルートファイルシステム・データ用の LVM パーティションを使用します。以下は現在の PIB プラットフォームリリース（`3.0.0`）の既定値であり、すべてのリリースで固定ではありません。正確な構成は、選択したビルダーの `configs/images/image-params.yaml` と `image-stages.yaml` を確認してください。初回起動時に LVM パーティションとデータボリュームがデバイスの利用可能容量まで拡張されるため、ダウンロードしたディスクイメージは物理デバイスより小さい場合があります。

### 物理パーティション

| # | 名前 | サイズ | 形式 | 内容 |
|---|---|---|---|---|
| 1 | `boot.A` | 256 MiB | vFAT | スロット A の `fip.bin`、U-Boot、ブートスクリプト、カーネル FIT・デバイスツリー情報、U-Boot 環境 |
| 2 | `boot.B` | 256 MiB | vFAT | スロット B のブート成果物 |
| 3 | `lvm` | 初回起動の拡張後に残るデバイスの利用可能容量 | LVM 物理ボリューム | 下記の論理ボリューム |

### 論理ボリューム

論理ボリュームはパーティション 3 内にあります。

| ボリューム | サイズ | ファイルシステム | 用途 |
|---|---|---|---|
| `rootfs.A` | `minimal` は 1.5 GiB、`palette` は 5.5 GiB | ext4 | スロット A のルートファイルシステム |
| `rootfs.B` | `rootfs.A` と同じ | 内容書き込み後に ext4 | スロット B のルートファイルシステム。初期状態は `slots` に依存 |
| `data` | 両方の rootfs スロットの容量を確保した後の LVM 残容量 | ext4 | 汎用ストレージ。初回起動時に拡張 |

### スロットの初期状態

- **`slots: ab`（PIB の既定）：** 両方の rootfs ボリュームをディスクイメージ内に作成し、内容を書き込みます。
- **`slots: a`：** ディスクイメージには `rootfs.A` だけを含めます。初回起動時に `simaai-growlvm` が同じサイズの `rootfs.B` を作成してから `data` を拡張します。更新で内容を書き込むまで、スロット B にルートファイルシステムはありません。

`slots` は初期ディスクイメージの内容を制御する設定であり、A/B 更新機能は維持されます。更新は非アクティブなスロットに書き込みます。更新後は、両スロットのブート成果物とルートファイルシステムの内容が異なる場合があります。

## トラブルシューティング

- **loop または device-mapper にアクセスできない：** `pib doctor` を実行します。Docker は必要なデバイスと特権コンテナを許可する必要があります。
- **x86 で ARM64 設定に失敗する：** Linux Docker エンジンが特権 binfmt 登録を許可しているか確認します。
- **イメージ作成が中断した：** ビルドを停止し、`pib clean` で残存リソースを確認してから、必要に応じて `pib clean --yes` を実行します。同じホスト上の他の PIB プロジェクトにも影響する場合があります。
- **パッケージや初期構築の失敗：** `configs/images/mmdebstrap.log` とリポジトリへの接続を確認します。

## カスタマイズ

`image.yaml` を編集します。ボードサポートを開発する場合以外は、`configs/` のリリース既定値を変更しないでください。

```yaml
base: minimal
release: 3.0.0
version: 3.0.0.2
packages:
  add: [my-app]
  remove: []
overlay: overlay/
hooks: [hooks/enable-my-app.sh]
vendor: My Company
```

オーバーレイのファイルは権限を保持し、イメージ内では root 所有になります。オーバーレイはパッケージのインストール前に適用されるため、`/etc` 以外のファイルがパッケージによって置き換わる場合があります。インストール後に必要な変更にはフックを使用してください。


アプリケーションサービスを有効にするインストール後フックを作成します。

```sh
#!/bin/sh
set -eu
systemctl --root="$1" enable my-app.service
```


フックはパッケージのインストールと SiMa のフックの後に、指定順で `sh` によって実行されます。`$1` は rootfs のディレクトリです。その配下に書き込むか `systemctl --root="$1"` を使用します。`chroot "$1"` はイメージ内の ARM64 プログラムを実行します。フックには、英数字と `_ . / + -` のみを含むワークスペース相対パスを指定してください。

別のパッケージが必要とするパッケージを削除すると、APT の依存関係解決が失敗します。`swupdate` や palette の `kea` など、ボードのフックが必要とするものは保持してください。`palette` から `minimal` に変更すると、イメージサイズや既定のパッケージ構成も変わります。

カスタム Debian パッケージには、`image.yaml` の `debs.key` で受け入れられる分離署名が必要です。`pib sign-debs` は生成した Debian 署名鍵を使用します。既存の GPG 識別情報を使用する場合は、公開鍵を `keys/debs-signing.asc` にエクスポートし、外部でパッケージに署名してビルド前に `pib verify-debs` を実行します。

カーネルは特別な扱いです。`configs/images/image-params.yaml` にあるリリースのカーネルパッケージ名を維持します。PIB はそのカーネルを自動選択し、インストール済みカーネルは 1 つである必要があります。`pib package` は、こうしたカーネルパッケージを SiMa のカーネルソースまたは独自のカーネルソースからビルドします。[カーネルのビルド](#building-the-kernel)を参照してください。ローカルの tRoot、ATF、U-Boot 置換パッケージは拒否されます。パッケージの U-Boot は `fip.bin` 内のものと一致する必要があります。

`swu.description` と `swu.script` を指定すると、更新手順を置き換えられます。最初に `configs/images/files/` のリリース既定値をコピーしてください。バージョン・ハードウェア互換性のプレースホルダー、ハッシュ、必須のブート/SBOM メンバーを保持します。これらはインストール時にボードで動くため、復旧可能なボードで変更を試してください。

`--dev` は一時的な署名情報を使用し、通常配布用の `--sign` と併用できません。開発用に生成する顧客 CA/リーフ鍵と `--dev` モードは別のものです。

## カーネルをビルドする

`pib package` は、SiMa のパッケージビルダーである sbp を使い、SiMa の公開カーネルソースまたは独自のカーネルソースから Modalix カーネルをビルドして、カーネルの Debian パッケージを `custom-debs/` に置きます。palette プロジェクトでは、palette イメージに含まれるカーネルモジュールパッケージである smifb と lttng-modules も、そのカーネル向けに再ビルドします。PIB イメージには、これらのビルドで使用する ARM64 クロスツールチェーンが含まれています。そのため、イメージは約 0.6 GB 大きくなります。

```bash
pib keys fit
pib package -p linux
pib sign-debs
pib build --sign
```


`pib keys fit` は `keys/fit-signing.key` と `keys/fit-signing.crt` を一度作成します。`pib package` はその鍵でカーネルの FIT イメージに署名します。次に、カーネルソースを選択します。

| カーネルソース | 選択方法 |
|---|---|
| SiMa の公開リポジトリの `master` ブランチ | 既定：`https://github.com/SiMa-ai/simaai-linux.git` |
| 自分のフォーク、そのいずれかのブランチ、またはコミット | `--kernel-url https://github.com/<you>/simaai-linux.git --kernel-ref <branch>`、または `PIB_KERNEL_URL` と `PIB_KERNEL_REF` |
| 自分のコンピューター上のリポジトリ | `PIB_KERNEL_SRC=<path>`：チェックアウト中のブランチ、または `PIB_KERNEL_REF` |

実行のたびにブランチを確認し、その最新コミットをビルドします。このコミットは `pib package` が表示します。ブランチが更新されていれば、カーネルを再ビルドします。ビルドされるのはコミット済みの変更だけで、未コミットの変更があれば `pib package` が警告します。ビルドコンテナには認証情報がありません。公開リポジトリはトークンを含まない https URL で指定し、非公開リポジトリは読み取り専用でマウントされる `PIB_KERNEL_SRC` で指定してください。あるリポジトリからの初回ビルドでは、そのリポジトリ全体をダウンロードします。

リリースのカーネルバージョン（6.18.3）、その `simaai_modalix_defconfig` 設定、および SiMa の FIT パッケージングを維持してください。イメージにはリリースのカーネルパッケージ名のパッケージだけがインストールされるため、別のバージョンは除外されます。FIT（`boot/fitImage`）を含まないカーネルパッケージは、プレーンなカーネルイメージとして署名なしで起動し、`pib package` はこれについて警告します。また、カーネルの SiMa 固有ヘッダーをリリースのヘッダーと比較し、異なる場合は警告します。カメラ ISP や MLA ランタイムなど、SiMa のビルド済みソフトウェアはリリースのヘッダーを使ってビルドされています。現在、`master` ブランチには SiMa の 3.0 カーネルがあります。このカーネルには FIT パッケージングとリリースのヘッダーが含まれているため、どちらの警告も表示されません。

カーネルのビルドには約 30 分かかり、Docker ボリューム `pib-package-<uid>` 内で 6-8 GB を使用します。PIB イメージには sbp とそのパッケージ設定が含まれています。別のチェックアウト（`pkgbuild/` と `configs/packages/`）でビルドするには、`PIB_PKGBUILD_SRC` を設定してください。

## 署名

イメージは `signing.ca` を更新の信頼ルートとして組み込みます。既存ボードを更新するときも、その CA を維持してください。ワークスペース外の鍵を使用する例です。

```bash
cp /path/to/public-ca.crt keys/ca.crt
SWU_SIGNING_KEY=/path/to/private-signing.key \
SWU_SIGNING_CERT=/path/to/public-signing.crt pib sign
pib verify
```


ランチャーはディレクトリ全体ではなく、選択した各ファイルを読み取り専用でマウントします。`pib build --sign` も同じ変数を受け付けます。より強い分離が必要なら、秘密鍵を別の署名マシンに置き、ビルドと署名を独立して実行します。CA 秘密鍵はリーフ証明書の発行・更新にだけ必要です。通常のビルドプロジェクトではなくオフラインで保管します。

生成したリーフを更新するには、一時的に `ca.key` を `keys/` に戻し、初期設定と同じアルゴリズムで `pib keys renew --cn 'My Company Development'` を実行してから、CA 鍵を再びオフラインへ戻します。リーフ証明書の有効期間は 825 日です。

PKCS#11 には `pib sign --pkcs11 'pkcs11:...' --cert keys/swu-signing.crt` を使います。Docker ホストには pcscd とリーダードライバーが必要です。署名時にランチャーが利用可能な pcscd ソケットをマウントします。`PIB_PCSCD_DIR` で場所を変更できます。物理カード・トークンでの操作は、この移植では未検証です。macOS のホストソケットが Linux Docker VM から使用できるとは限りません。

暗号化する場合は `pib keys payload` を実行し、ビルド前に `encryption: {key: keys/payload.key}` を設定してから `pib sign --encrypt` を使います。イメージ自体に復号鍵が含まれるため、イメージを抽出できる相手からの保護にはなりません。暗号化ではビルドと署名を分けてください。`build --sign` は通常の非暗号化署名です。

## ボードへのアクセス

新しいイメージを書き込む前に、認証情報か許可済み SSH 鍵を設定します。root と sima のパスワードハッシュを指定する場合は、保護された資格情報ファイルをプロジェクト外に作成し、`PIB_CREDENTIALS` で指定します。

```bash
mkdir -p ../secure
chmod 700 ../secure
(umask 077; printf 'root:%s\nsima:%s\n' \
  "$(openssl passwd -6)" "$(openssl passwd -6)" > ../secure/credentials)
PIB_CREDENTIALS="$(cd ../secure && pwd)/credentials" pib build --sign
```


この方法ではホストに OpenSSL が必要です。パスワードは入力を求められ、保存されるのはハッシュだけです。root の SSH 接続は鍵認証に限定されます。代わりに、許可された公開鍵を `overlay/root/.ssh/authorized_keys` に置くこともできます。ディレクトリを 700、ファイルを 600 にしてください。各ボードは初回起動時に独自の SSH ホスト鍵を生成します。

root SSH が必要な場合は、ビルド前にプロジェクト内で次を実行します。承認された**公開鍵**のみを追記し、秘密鍵をイメージに含めないでください。

```bash
mkdir -p overlay/root/.ssh
chmod 700 overlay/root/.ssh
cat "$HOME/.ssh/id_ed25519.pub" >> overlay/root/.ssh/authorized_keys
chmod 600 overlay/root/.ssh/authorized_keys
```

`PIB_CREDENTIALS` で root パスワードを設定しても、SSH の root パスワード認証は無効です。1 行につき 1 公開鍵を許可します。展開後は許可済み鍵で `ssh root@<board-address>` を使用できます。既存ボードでは永続オーバーレイに SSH 設定が残る場合があります。

## SWU をインストールする

以下はボードを変更するコマンドです。**署名済み** `.swu` と対象ボードを明示的に選んでください。ボードは互換性のある SiMa/PIB eLxr イメージで動作し、sudo を使用できる `sima` の SSH アクセスが必要です。

初回は、認可されたプロビジョニング手順で CA の信頼を設定します。開発用ボードでの初期設定例を示します。

```bash
BOARD=192.0.2.10
SWU=out/your-image.swu
scp "$SWU" keys/ca.crt "sima@$BOARD:/tmp/"
ssh -t "sima@$BOARD" sudo swupdate -i "/tmp/$(basename "$SWU")" \
  -k /tmp/ca.crt -e update,full
ssh -t "sima@$BOARD" sudo reboot
```


以降の更新では、インストール済み CA とバージョンポリシーを使用します。

```bash
scp "$SWU" "sima@$BOARD:/tmp/"
ssh -t "sima@$BOARD" sudo simaai-update "/tmp/$(basename "$SWU")" -e update,full
ssh -t "sima@$BOARD" sudo reboot
```


更新先は非アクティブスロットです。ブート選択とウォッチドッグによるロールバックはプラットフォームのブート・更新実装に依存するため、使用するイメージでハードウェア検証が必要です。既定ではボードの書き込み可能オーバーレイを保持します。オーバーレイを初期化する更新では、ローカルの認証情報や設定が消える場合があります。初回 eMMC 書き込みはプラットフォームの復旧手順に従ってください。SWU は raw ディスクイメージではありません。

現在のレイアウトは GPT の `boot.A`、`boot.B` と、rootfs A/B およびデータを含む LVM パーティションです。旧来の raw パーティション用 U-Boot 書き込み手順を適用しないでください。正確な構成は各リリースのボードテンプレートで定義されます。

## 新しいプラットフォームリリース

対応するビルダーイメージを取得してランチャーを取り出し、`pib init` で新しいプロジェクトを作成します。元の CA と署名情報は維持してください。オーバーレイとフックを移行し、新しい `release` と `version` を保持したまま顧客設定を `image.yaml` にマージします。

新しいプラットフォームと互換性のある Debian パッケージだけを移してください。独自の更新スクリプト・定義は、そのリリースの既定値を基に更新します。古い `configs/` を丸ごとコピーしないでください。旧リリースを保守する場合は、以前のプロジェクトと固定したランチャー・イメージ参照も保存します。
