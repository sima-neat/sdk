# Palette Image Builder 참조

먼저 [맞춤형 이미지 워크플로](palette-image-builder.md)를 읽으세요. 이 페이지는 선택 기능과 보드 작업을 설명합니다. 컨테이너 유지 관리는 [빌더 README](../palette-image-builder/README.md)를 확인하세요.

## 설치

표준 설치 명령은 `sima-cli neat install sdk/pib`입니다. 선택한 SDK 배포의 `pib/` 메타데이터를 읽어 검증된 멀티플랫폼 이미지를 가져오고 이식 가능한 호스트 런처를 설치합니다. Python은 sima-cli 환경을 사용하고 빌드 도구는 컨테이너에 남습니다. 기본 대상은 main이며 `sdk/pib@develop`과 `sdk/pib@<release>`로 다른 배포를 선택합니다.

Windows에서는 Docker Desktop의 Linux 컨테이너 모드와 PowerShell을 사용하세요. 설치 프로그램은 `pib.cmd` 진입점을 만들고 사용자 PATH를 갱신합니다. Linux/macOS에서는 `~/.local/bin`에 설치하고 필요하면 셸 프로필을 갱신합니다. amd64/arm64 이미지는 자동 선택됩니다. Linux Docker 호스트는 루프 장치, device-mapper, binfmt_misc 커널 기능을 지원해야 하며 데스크톱 VM도 이를 제공해야 합니다. `pib doctor`가 확인합니다. 전체 이미지 생성은 네이티브 Linux x86/ARM과 Apple Silicon/Colima에서 검증되었습니다. Windows 설치 테스트는 Windows 전체 이미지 생성 검증이 아닙니다.

sima-cli 없이 Docker를 수동 사용하려면 공개 이미지를 가져와 런처를 추출하세요. Python 3이 PATH에 있어야 합니다.

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


x86 이미지에는 에뮬레이터가 포함됩니다. 특권 PIB 시작 시 정상 ARM64 핸들러가 없으면 Docker 호스트의 Linux 커널에 등록합니다. 기존 정상 핸들러는 유지하고 네이티브 ARM64에서는 등록하지 않습니다. Docker 호스트 재부팅 뒤에도 자동 재설정됩니다. 호스트에 패키지를 설치하지 않습니다.

## 환경 변수

호스트에서 `pib`를 실행하는 셸에 설정합니다. 파일은 Docker에서 접근 가능해야 합니다. 인증 및 서명 파일은 사용하는 명령에만 읽기 전용으로 마운트합니다. `PIB_CONFIGS`는 상위 폴더를 읽기 전용으로, `PIB_DEB_CACHE`는 쓰기 가능으로 마운트합니다.

| 변수 | 사용 명령 | 용도 |
|---|---|---|
| `PIB_IMAGE` | 모든 명령 | 태그 또는 다이제스트로 설치된 컨테이너 이미지를 재정의합니다. |
| `PIB_CREDENTIALS` | `pib build` | `root:<hash>`, `sima:<hash>` 암호 해시 파일. 미설정 시 새 이미지는 두 암호를 잠급니다. 기존 보드는 영구 오버레이에 인증 정보를 유지할 수 있습니다. |
| `SWU_SIGNING_KEY`, `SWU_SIGNING_CERT` | `pib sign`, `pib build --sign` | 외부 서명 키와 인증서. 키는 `pkcs11:` URI도 가능합니다. 기본값은 프로젝트 설정이며 인증서는 이미지가 신뢰하는 CA로 연결되어야 합니다. |
| `PIB_CONFIGS` | `pib init` | 고급: 내장 설정 대신 외부 이미지 설정 디렉터리를 사용합니다. |
| `PIB_PCSCD_DIR` | 서명 명령 | pcscd 소켓 폴더. 기본값 `/run/pcscd`. Linux 컨테이너에서 소켓에 접근할 수 있어야 합니다. |
| `PIB_DEB_CACHE` | `pib build`, `pib shell` | 검증된 Debian 다운로드의 호스트 캐시. 매 빌드마다 인증된 메타데이터의 해시와 크기를 검사합니다. |
| `PIB_KERNEL_URL`, `PIB_KERNEL_REF` | `pib package` | 실행할 때마다 빌드할 커널 저장소(인증 정보가 없는 https URL)와 브랜치 또는 커밋. `--kernel-url`과 `--kernel-ref`는 한 번의 실행에 한해 이 값을 재정의합니다. |
| `PIB_KERNEL_SRC` | `pib package` | 사용자 커널이 담긴 호스트의 Git 저장소(체크아웃 또는 bare 저장소). 읽기 전용으로 마운트됩니다. 비공개 저장소나 어디에도 푸시하지 않은 커밋에 사용하세요. |
| `PIB_PKGBUILD_SRC` | `pib package` | sbp(`pkgbuild/`)와 sbp의 패키지 설정(`configs/packages/`)이 들어 있는 체크아웃. PIB 이미지에 포함된 것 대신 사용됩니다. 이미지에 이 둘이 포함될 때까지 필요합니다. 이 두 디렉터리만 읽기 전용으로 마운트됩니다. |
| `PIB_PACKAGE_JOBS`, `PIB_CCACHE_SIZE`, `PIB_PACKAGE_VOLUME` | `pib package` | 병렬 컴파일 작업 수. 컴파일러 캐시 크기(기본값 `5G`). sbp의 작업 트리, 패키지 저장소, 캐시를 위한 Docker 볼륨(기본값 `pib-package-<uid>`). |

## 명령

이미지는 빌더에서 사용 가능한 CPU 코어를 활용하는 pigz로 압축됩니다. 출력은 gzip 호환이며 서명과 검증은 실제 압축 페이로드를 대상으로 합니다.

빌드 간 Debian 다운로드를 재사용하려면 호스트 캐시 디렉터리를 지정하세요.

```bash
export PIB_DEB_CACHE="$HOME/.cache/sima/pib-debs"
pib build --sign
```


패키지 바이트만 캐시합니다. 각 bootstrap은 현재 저장소 메타데이터를 다운로드하고 인증한 뒤 SHA256과 크기로 캐시를 확인합니다. 손상된 파일은 버리고 다시 다운로드합니다. 루트 파일시스템, 패키지 설치, 사용자 지정 훅, 서명, 검증은 매번 수행합니다. 캐시에는 사용자 지정 패키지도 포함될 수 있으므로 개인 사용자 디렉터리에 보관하세요.

| 명령 | 용도 |
|---|---|
| `pib doctor` | 도구, 공간, 루프 장치, device-mapper, 에뮬레이션 확인 |
| `pib init DIR --flavor minimal` | 프로젝트 생성. minimal, palette 지원 |
| `pib init DIR --example custom-image` | 완전한 샘플 명세와 입력 복사 |
| `pib shell` | 현재 프로젝트를 마운트한 컨테이너 셸 열기 |
| `pib keys init --cn NAME` | CA, SWU 리프 인증서, Debian 서명 정보 생성 |
| `pib keys renew --cn NAME` | 같은 CA로 리프 인증서 갱신 |
| `pib keys fit` | `pib package`가 빌드한 커널 FIT 이미지를 서명하는 키 쌍 생성 |
| `pib package -p linux` | 커널, 그리고 palette의 커널 모듈 패키지를 `custom-debs/`에 빌드 |
| `pib sign-debs` / `pib verify-debs` | 사용자 지정 Debian 패키지 서명/검사 |
| `pib build [--sign] [--supplier NAME]` | 빌드하고 선택적으로 서명 및 검증 |
| `pib sign [FILE]` | 번들 서명. 기본값은 현재 프로젝트 버전 |
| `pib verify [FILE] [--ca CRT] [--manifest JSON]` | 서명 및 페이로드 검증. 프로젝트 기본값과 인접 매니페스트 자동 선택 |
| `pib diff --against MANIFEST` | 이전 빌드와 패키지 차이 확인 |
| `pib clean [--yes]` | 남은 빌드 루프 장치와 볼륨 그룹 검사/제거 |

모든 명령은 컨테이너 안에서 실행됩니다. 호스트 런처는 Docker, 작업 공간 마운트, 명시적으로 선택한 외부 파일만 처리합니다. `build`, `doctor`, `clean`, 대화형 셸은 특권 장치 접근을 사용합니다. 서명, 검증, 키 생성, 프로젝트 생성에는 필요하지 않습니다. `pib package`는 특권 없이 실행되며, 프로젝트에는 `custom-debs/`를 제외하고 읽기 전용으로 접근합니다. `keys/`에서는 커널 FIT 키 쌍에만 접근합니다.

## 빌드 결과물

| 파일 | 기술적 목적 |
|---|---|
| `*.swu` | 서명된 업데이트 번들 |
| `*.unsigned.swu` | 별도 서명 단계의 입력 |
| `*.img.gz` | 프로비저닝 또는 복구용 압축 디스크 이미지 |
| `*-boot0.be` | 관련 tRoot 페이로드. 플랫폼 프로비저닝 절차를 따르세요 |
| `*.manifest.json` | 패키지 버전, 출처, 부트 페이로드 이력 |
| `*.cdx.json` | CycloneDX 소프트웨어 구성 명세 |
| `SHA256SUMS` | 아티팩트 체크섬 |

`out/`에 이전 빌드가 있어도 `pib sign`과 `pib verify`는 현재 `image.yaml` 버전을 선택합니다. 같은 버전을 다시 빌드하면 이미 서명된 SWU를 포함한 결과물을 덮어씁니다. 후속 업데이트에는 버전을 올리세요.

## 미디어 및 파티션 구조

Modalix eMMC/SD 이미지는 GPT 부트 파티션과 루트 파일 시스템 및 데이터용 LVM 파티션을 사용합니다. 아래 값은 현재 PIB 플랫폼 릴리스(`3.0.0`)의 기본값이며 모든 릴리스에 고정된 크기가 아닙니다. 정확한 구조는 선택한 빌더의 `configs/images/image-params.yaml`과 `image-stages.yaml`을 확인하세요. 첫 부팅 시 LVM 파티션과 데이터 볼륨이 장치의 가용 용량까지 확장되므로 다운로드한 디스크 이미지는 물리 장치보다 작을 수 있습니다.

### 물리 파티션

| # | 이름 | 크기 | 형식 | 내용 |
|---|---|---|---|---|
| 1 | `boot.A` | 256 MiB | vFAT | 슬롯 A의 `fip.bin`, U-Boot, 부트 스크립트, 커널 FIT/장치 트리 데이터, U-Boot 환경 |
| 2 | `boot.B` | 256 MiB | vFAT | 슬롯 B의 부트 아티팩트 |
| 3 | `lvm` | 첫 부팅 확장 후 남은 장치 가용 용량 | LVM 물리 볼륨 | 아래 논리 볼륨 포함 |

### 논리 볼륨

논리 볼륨은 파티션 3 안에 있습니다.

| 볼륨 | 크기 | 파일 시스템 | 목적 |
|---|---|---|---|
| `rootfs.A` | `minimal`은 1.5 GiB, `palette`는 5.5 GiB | ext4 | 슬롯 A 루트 파일 시스템 |
| `rootfs.B` | `rootfs.A`와 동일 | 내용 기록 후 ext4 | 슬롯 B 루트 파일 시스템. 초기 상태는 `slots`에 따라 결정 |
| `data` | 두 rootfs 슬롯 공간을 예약한 뒤 남은 LVM 용량 | ext4 | 일반 저장소. 첫 부팅 시 확장 |

### 슬롯 초기 구성

- **`slots: ab`(PIB 기본값):** 디스크 이미지에 두 rootfs 볼륨을 생성하고 내용을 기록합니다.
- **`slots: a`:** 디스크 이미지는 `rootfs.A`만 포함합니다. 첫 부팅 시 `simaai-growlvm`이 같은 크기의 `rootfs.B`를 만든 후 `data`를 확장합니다. 업데이트가 내용을 기록하기 전에는 슬롯 B에 루트 파일 시스템이 없습니다.

`slots`는 초기 디스크 이미지의 구성을 제어하며 A/B 업데이트 기능을 제거하지 않습니다. 업데이트는 비활성 슬롯에 기록합니다. 업데이트 후 두 슬롯의 부트 아티팩트와 루트 파일 시스템은 서로 다를 수 있습니다.

## 문제 해결

- **loop 또는 device-mapper 접근 누락:** `pib doctor`를 실행하세요. Docker는 필요한 장치와 특권 컨테이너를 허용해야 합니다.
- **x86에서 ARM64 설정 실패:** Linux Docker 엔진이 특권 binfmt 등록을 허용하는지 확인하세요.
- **이미지 빌드 중단:** 빌드를 멈추고 `pib clean`으로 잔여 리소스를 확인한 후 필요하면 `pib clean --yes`를 사용하세요. 같은 호스트의 다른 PIB 프로젝트에도 영향을 줄 수 있습니다.
- **패키지 또는 부트스트랩 실패:** `configs/images/mmdebstrap.log`와 저장소 연결을 확인하세요.

## 사용자 지정

`image.yaml`을 편집하세요. 보드 지원을 개발하는 경우가 아니면 `configs/`의 릴리스 기본값을 유지합니다.

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

오버레이 파일은 권한을 유지하며 이미지에서 root 소유가 됩니다. 오버레이는 패키지 설치 전에 적용되므로 패키지가 `/etc` 외부의 파일을 교체할 수 있습니다. 설치 이후에 필요한 변경에는 설치 후 훅을 사용하세요.


애플리케이션 서비스를 활성화하는 설치 후 훅을 만드세요.

```sh
#!/bin/sh
set -eu
systemctl --root="$1" enable my-app.service
```


훅은 SiMa 훅과 패키지 설치 후 지정한 순서로 `sh`를 통해 실행됩니다. `$1`은 rootfs 디렉터리입니다. 그 아래에 쓰거나 `systemctl --root="$1"`을 사용하세요. `chroot "$1"`은 이미지의 ARM64 프로그램을 실행합니다. 훅에는 영숫자와 `_ . / + -`만 포함하는 작업 공간 상대 경로를 사용하세요.

다른 패키지의 필수 의존성을 제거하면 APT 해결이 실패합니다. `swupdate`나 palette의 `kea`처럼 보드 훅에 필요한 패키지는 유지하세요. `palette`에서 `minimal`로 변경하면 이미지 크기와 기본 패키지 구성도 바뀝니다.

사용자 지정 Debian 패키지는 `image.yaml`의 `debs.key`로 검증할 수 있는 분리 서명이 필요합니다. `pib sign-debs`는 생성한 Debian 서명 키를 사용합니다. 기존 GPG 서명 정보를 쓰려면 공개 키를 `keys/debs-signing.asc`로 내보내고 외부에서 패키지를 서명한 뒤 빌드 전에 `pib verify-debs`를 실행하세요.

커널 패키지는 특별 취급됩니다. `configs/images/image-params.yaml`에 있는 릴리스 커널 패키지 이름을 유지하세요. PIB가 자동 선택하며 설치된 커널은 하나여야 합니다. `pib package`는 SiMa의 커널 소스나 사용자의 커널 소스로 이러한 패키지를 빌드합니다. [커널 빌드](#building-the-kernel)를 참조하세요. 로컬 tRoot, ATF, U-Boot 교체 패키지는 거부합니다. 패키지 U-Boot는 `fip.bin` 내부 U-Boot와 일치해야 합니다.

`swu.description`과 `swu.script`는 업데이트 절차를 바꿀 수 있습니다. 먼저 `configs/images/files/`의 릴리스 기본값을 복사하세요. 버전/하드웨어 호환성 자리표시자, 해시, 필수 부팅/SBOM 항목을 유지합니다. 이 스크립트는 설치할 때 보드에서 실행되므로 복구 가능한 보드에서 변경 사항을 테스트하세요.

`--dev` 빌드는 임시 서명 정보를 사용하며 일반 배포용 `--sign`과 함께 사용할 수 없습니다. 개발용 고객 CA/리프 키와 `--dev` 모드는 별개입니다.

## 커널 빌드

`pib package`는 SiMa의 패키지 빌더인 sbp를 사용해 SiMa의 공개 커널 소스나 사용자의 커널 소스로 Modalix 커널을 빌드하고, 커널의 Debian 패키지를 `custom-debs/`에 넣습니다. palette 프로젝트에서는 palette 이미지에 포함되는 커널 모듈 패키지인 smifb와 lttng-modules도 해당 커널에 맞춰 다시 빌드합니다. PIB 이미지에는 이러한 빌드에 사용하는 ARM64 크로스 툴체인이 포함되어 있어, 이미지가 약 0.6 GB 더 커집니다.

```bash
pib keys fit
pib package -p linux
pib sign-debs
pib build --sign
```

`pib keys fit`은 `keys/fit-signing.key`와 `keys/fit-signing.crt`를 한 번 생성합니다. `pib package`는 이 키로 커널의 FIT 이미지를 서명합니다. 그런 다음 소스를 선택하세요.

| 커널 소스 | 선택 방법 |
|---|---|
| SiMa의 공개 저장소, `master` 브랜치 | 기본값: `https://github.com/SiMa-ai/simaai-linux.git` |
| 사용자의 포크, 그 포크의 브랜치 중 하나 또는 커밋 | `--kernel-url https://github.com/<you>/simaai-linux.git --kernel-ref <branch>` 또는 `PIB_KERNEL_URL`과 `PIB_KERNEL_REF` |
| 사용자 컴퓨터의 저장소 | `PIB_KERNEL_SRC=<path>`: 해당 저장소에서 체크아웃된 브랜치 또는 `PIB_KERNEL_REF` |

실행할 때마다 브랜치를 조회해 최신 커밋을 빌드하며, `pib package`가 그 커밋을 출력합니다. 브랜치가 이동했으면 커널이 다시 빌드됩니다. 커밋된 변경 사항만 빌드되며, 커밋되지 않은 변경 사항이 있으면 `pib package`가 경고합니다. 빌드 컨테이너에는 인증 정보가 없습니다. 공개 저장소는 토큰이 없는 https URL로 지정하고, 비공개 저장소는 읽기 전용으로 마운트되는 `PIB_KERNEL_SRC`로 지정하세요. 저장소에서 처음 빌드할 때는 그 저장소 전체를 다운로드합니다.

릴리스 커널의 버전(6.18.3)과 `simaai_modalix_defconfig` 설정, 그리고 SiMa의 FIT 패키징을 유지하세요. 이미지는 릴리스의 커널 패키지 이름만 설치하므로 다른 버전은 제외됩니다. FIT 이미지(`boot/fitImage`)가 없는 커널 패키지는 서명되지 않은 일반 커널 이미지로 부팅되며, `pib package`가 이에 대해 경고합니다. 또한 커널의 SiMa 고유 헤더를 릴리스의 헤더와 비교하고, 서로 다르면 경고합니다. 카메라 ISP와 MLA 런타임 같은 SiMa의 사전 빌드된 소프트웨어는 릴리스의 헤더를 기준으로 빌드됩니다. 현재 `master` 브랜치에는 SiMa의 3.0 커널이 있습니다. 이 커널에는 FIT 패키징과 릴리스의 헤더가 있으므로 두 경고 모두 나타나지 않습니다.

커널 빌드에는 약 30분이 걸리며 Docker 볼륨 `pib-package-<uid>`에 6-8 GB가 필요합니다. sbp 자체가 PIB 이미지에 포함될 때까지는 sbp가 들어 있는 체크아웃(`pkgbuild/`와 `configs/packages/`)을 `PIB_PKGBUILD_SRC`로 지정하세요.

## 서명

이미지는 `signing.ca`를 업데이트 신뢰 루트로 포함합니다. 기존 보드 이미지를 갱신할 때도 CA를 유지하세요. 작업 공간 외부의 키를 사용하려면 다음과 같이 합니다.

```bash
cp /path/to/public-ca.crt keys/ca.crt
SWU_SIGNING_KEY=/path/to/private-signing.key \
SWU_SIGNING_CERT=/path/to/public-signing.crt pib sign
pib verify
```


런처는 전체 디렉터리 대신 선택한 각 파일만 읽기 전용으로 마운트합니다. `pib build --sign`도 같은 변수를 지원합니다. 더 강한 분리가 필요하면 개인 키를 별도 서명 컴퓨터에 보관하고 빌드와 서명을 따로 실행하세요. CA 개인 키는 리프 인증서 발급/갱신에만 필요하므로 일상 빌드 프로젝트가 아닌 오프라인에 보관합니다.

생성한 리프 인증서를 갱신하려면 `ca.key`를 일시적으로 `keys/`에 복원하고 초기 설정과 같은 알고리즘으로 `pib keys renew --cn 'My Company Development'`를 실행한 뒤 CA 키를 다시 오프라인으로 옮깁니다. 리프 인증서 유효 기간은 825일입니다.

PKCS#11에는 `pib sign --pkcs11 'pkcs11:...' --cert keys/swu-signing.crt`를 사용합니다. Docker 호스트에 pcscd와 리더 드라이버가 필요합니다. 런처는 서명 시 사용할 수 있는 pcscd 소켓을 마운트하며 `PIB_PCSCD_DIR`로 위치를 바꿀 수 있습니다. 실제 카드/토큰은 이 포팅에서 테스트하지 않았습니다. macOS 호스트 소켓이 Linux Docker VM에서도 제공된다는 보장은 없습니다.

암호화된 페이로드는 `pib keys payload`를 실행하고 빌드 전에 `encryption: {key: keys/payload.key}`를 설정한 다음 `pib sign --encrypt`를 사용합니다. 생성된 이미지에 복호화 키가 포함되므로 이미지를 추출할 수 있는 공격자로부터 보호하지는 않습니다. 암호화에는 별도 빌드/서명 단계를 사용하세요. `build --sign`은 일반 비암호화 서명 경로를 사용합니다.

## 보드 접근

새 이미지를 플래시하기 전에 인증 정보나 허용된 SSH 키를 구성하세요. root와 sima 비밀번호 해시를 제공하려면 프로젝트 밖에 보호된 파일을 만들고 `PIB_CREDENTIALS`로 지정합니다.

```bash
mkdir -p ../secure
chmod 700 ../secure
(umask 077; printf 'root:%s\nsima:%s\n' \
  "$(openssl passwd -6)" "$(openssl passwd -6)" > ../secure/credentials)
PIB_CREDENTIALS="$(cd ../secure && pwd)/credentials" pib build --sign
```


이 선택 방식은 호스트에 OpenSSL이 필요합니다. 비밀번호를 입력받고 해시만 저장합니다. root SSH 접근은 키 전용입니다. 또는 승인된 공개 키를 `overlay/root/.ssh/authorized_keys`에 배치하세요. 디렉터리는 700, 파일은 600으로 설정합니다. 보드마다 첫 부팅 시 고유 SSH 호스트 키를 생성합니다.

선택적으로 root SSH가 필요하면 빌드 전에 프로젝트 폴더에서 다음을 실행합니다. 승인된 **공개 키**만 추가하고 개인 키는 이미지에 넣지 마세요.

```bash
mkdir -p overlay/root/.ssh
chmod 700 overlay/root/.ssh
cat "$HOME/.ssh/id_ed25519.pub" >> overlay/root/.ssh/authorized_keys
chmod 600 overlay/root/.ssh/authorized_keys
```

`PIB_CREDENTIALS`로 root 암호를 설정해도 SSH root 암호 인증은 비활성화됩니다. 한 줄에 공개 키 하나를 허용합니다. 배포 후 승인된 키로 `ssh root@<board-address>`에 연결합니다. 기존 보드는 영구 오버레이에 SSH 설정을 유지할 수 있습니다.

## SWU 설치

아래 명령은 보드를 변경합니다. **서명된** `.swu`와 의도한 보드를 명시적으로 선택하세요. 보드는 호환되는 SiMa/PIB eLxr 이미지를 실행하며 `sima` 계정의 SSH와 sudo 접근을 제공해야 합니다.

첫 설치에서는 승인된 프로비저닝 절차로 CA 신뢰를 설정합니다. 가이드의 개발 보드 초기 설정은 다음과 같습니다.

```bash
BOARD=192.0.2.10
SWU=out/your-image.swu
scp "$SWU" keys/ca.crt "sima@$BOARD:/tmp/"
ssh -t "sima@$BOARD" sudo swupdate -i "/tmp/$(basename "$SWU")" \
  -k /tmp/ca.crt -e update,full
ssh -t "sima@$BOARD" sudo reboot
```


후속 업데이트는 보드에 설치된 CA와 버전 정책을 사용합니다.

```bash
scp "$SWU" "sima@$BOARD:/tmp/"
ssh -t "sima@$BOARD" sudo simaai-update "/tmp/$(basename "$SWU")" -e update,full
ssh -t "sima@$BOARD" sudo reboot
```


업데이트 대상은 비활성 슬롯입니다. 부팅 선택과 watchdog 롤백은 플랫폼 부팅/업데이트 구현에 의존하므로 실제 이미지로 하드웨어 검증이 필요합니다. 기본 업데이트는 보드의 쓰기 가능한 오버레이를 유지합니다. 오버레이 초기화 업데이트는 로컬 인증 정보/설정을 지울 수 있습니다. 초기 eMMC 플래시는 플랫폼 복구 가이드를 따르세요. SWU는 raw 디스크 이미지가 아닙니다.

현재 레이아웃은 GPT `boot.A`, `boot.B`와 rootfs A/B 및 데이터를 포함하는 LVM 파티션을 사용합니다. 이전 raw 파티션용 U-Boot 플래시 명령을 이 레이아웃에 적용하지 마세요. 정확한 크기와 구조는 릴리스 보드 템플릿에 정의됩니다.

## 새 플랫폼 릴리스

적절한 빌더 이미지를 가져와 런처를 추출한 다음 `pib init`으로 새 프로젝트를 만듭니다. 기존 CA와 서명 정보를 유지하세요. 오버레이/훅을 옮기고 새 `release`와 `version`을 유지하면서 고객 설정을 새 `image.yaml`에 병합합니다.

새 플랫폼과 호환되는 Debian 패키지만 복사하세요. 사용자 지정 업데이트 스크립트/정의는 해당 릴리스 기본값에 맞춰 갱신합니다. 이전 `configs/` 전체를 덮어쓰지 마세요. 이전 릴리스를 유지 관리할 때는 기존 프로젝트와 고정된 런처/이미지 참조를 보관합니다.
