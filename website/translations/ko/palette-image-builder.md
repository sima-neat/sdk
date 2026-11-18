# 사용자 지정 Modalix 이미지 만들기

Palette Image Builder(PIB)는 Modalix용 사용자 지정 eLxr 이미지를 만듭니다. Palette SDK 저장소에서 관리하는 별도의 Docker 컨테이너로 제공됩니다. sima-cli로 설치하며, 기본 SDK 컨테이너는 필요하지 않습니다.

하나의 프로젝트에서 두 가지 배포 형식을 생성합니다.

- **`.swu`**: 실행 중인 보드에 적용하는 서명된 업데이트 번들.
- **`.img.gz`**: 초기 프로비저닝이나 복구에 사용하는 전체 디스크 이미지.

## 1. PIB 설치

[sima-cli](https://docs.sima-neat.com/getting-started/installation)와 Docker를 설치한 다음 실행합니다.

```bash
sima-cli neat install sdk/pib
pib doctor
```


설치 프로그램은 호스트에 맞는 x86_64 또는 ARM64 컨테이너를 다운로드하고 Linux, macOS, Windows에 `pib` 명령을 설치합니다. PATH가 변경되면 새 터미널을 여세요. PIB는 Linux 컨테이너에서 실행되므로 Docker를 시작하고 이미지 생성에 필요한 특권 접근을 허용해야 합니다. x86 Docker 호스트에서는 포함된 ARM64 에뮬레이터가 자동 설정됩니다.

로컬 프로젝트 폴더에 `minimal`은 10 GiB 이상, `palette`는 20 GiB 이상의 여유 공간을 확보하고 Docker 저장소에도 비슷한 공간을 마련하세요. 빌드 중 Debian/eLxr 및 SiMa 패키지 저장소에 연결할 수 있어야 합니다. 생성되는 보드 이미지는 ARM64입니다.

`sdk/pib`는 main에서 가장 최근에 게시된 패키지를 선택합니다. 다른 SDK 브랜치나 릴리스는 SDK와 같은 구문으로 지정합니다. 예: `sima-cli neat install sdk/pib@develop`. 수동 Docker 설치와 호스트 요구 사항은 [설치 참조](palette-image-builder-reference.md#installation)를 확인하세요.

## 2. 이미지 프로젝트 만들기

```bash
pib init my-image --flavor minimal
cd my-image
```


데스크톱과 더 많은 패키지가 필요하면 `--flavor palette`를 사용하세요. 이미지의 플랫폼 릴리스는 선택한 컨테이너에서 결정됩니다. 프로젝트에는 다음 항목이 있습니다.

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


이후 명령은 프로젝트 디렉터리에서 실행합니다. 파일이 마운트된 셸을 열려면 `pib shell`을 실행하세요. 컨테이너 셸에서는 `pib`를 직접 실행하고, `exit`로 호스트에 돌아갑니다.

애플리케이션 패키지, 설정 오버레이, 서비스 활성화 훅을 포함한 실행 가능한 예제를 사용하려면 `pib init my-image --example custom-image`를 실행하세요. [예제 안내](palette-image-builder-example.md)에서 전체 과정을 설명합니다. CI도 저장소에 있는 동일한 `image.yaml`을 두 아키텍처에서 빌드합니다. 예제는 컨테이너에 포함되어 있어 저장소를 복제할 필요가 없습니다.

## 3. 최초 서명 설정

개발용 테스트 CA와 서명 정보를 생성합니다.

```bash
pib keys init --cn 'My Company Development'
```


설정 후 `keys/ca.key`를 안전한 오프라인 위치로 옮기세요. 서명용 리프 인증서와 개인 키는 `keys/`에 남습니다. 생성되는 `.gitignore`는 개인 키와 빌드 출력을 제외합니다. 서명 정보를 안전하게 백업하세요. 기존 보드가 해당 CA를 신뢰하므로 새 프로젝트나 플랫폼 릴리스로 이동할 때도 같은 CA를 유지해야 합니다.

프로덕션에서는 조직의 서명 정보를 사용하세요. [외부 키 및 인증서 갱신](palette-image-builder-reference.md#signing)을 참고하세요. 컨테이너에는 SiMa 프로덕션 서명 키가 포함되지 않습니다.

## 4. 이미지 사용자 지정

첫 빌드에서는 편집기로 `overlay/etc/motd`를 만듭니다.

```text
My custom Modalix image
```


`overlay/` 아래 파일은 권한을 유지하며 이미지 안에서는 root 소유가 됩니다. 오버레이는 패키지 설치 전에 적용되므로 패키지가 `/etc` 이외의 파일을 덮어쓸 수 있습니다. 설치 후 변경이 필요하면 훅을 사용하세요.

애플리케이션을 Debian 패키지로 설치하려면 다음을 실행합니다.

```bash
cp /path/to/my-app_1.0_arm64.deb custom-debs/
pib sign-debs
pib verify-debs
```


파일명이 아닌 **패키지 이름**을 `image.yaml`에 추가합니다.

```yaml
packages:
  add: [my-app]
  remove: []
```


패키지 아키텍처는 `arm64` 또는 `all`이어야 합니다. 커널 교체, 패키지 제거, 서비스 활성화, 사용자 지정 업데이트 스크립트는 [사용자 지정 참조](palette-image-builder-reference.md#customization)를 확인하세요.

## 5. 서명된 업데이트 빌드

```bash
pib build --sign
```


이미지를 빌드하고 설정한 서명 정보로 SWU에 서명한 다음 서명, 페이로드 해시, 빌드 매니페스트를 검증합니다. 일반적으로 호스트와 네트워크에 따라 몇 분이 소요됩니다. 결과는 `out/`에 생성됩니다.

| 출력 | 용도 |
|---|---|
| `*.swu` | 서명된 업데이트 번들 |
| `*.unsigned.swu` | 별도 서명 단계에 사용할 번들 |
| `*.img.gz` | 프로비저닝/복구용 압축 디스크 이미지 |
| `*-boot0.be` | 연결된 tRoot 페이로드 |
| `*.manifest.json` | 패키지 버전/출처 및 부팅 페이로드 출처 정보 |
| `*.cdx.json` | CycloneDX 소프트웨어 자재 명세서 |
| `SHA256SUMS` | 아티팩트 체크섬 |

파일명을 직접 찾지 않고 다시 검증하려면 다음을 실행합니다.

```bash
pib verify
```


CI 또는 별도 서명 시스템에서는 `pib build`, `pib sign`, `pib verify`를 각각 실행할 수 있습니다. `out/`에 이전 버전이 있어도 `pib sign`과 `pib verify`는 현재 `image.yaml` 버전을 선택합니다.

다음 빌드 전에 `image.yaml`의 `version` 마지막 숫자를 증가시키세요. 예를 들어 `3.0.0.1`을 `3.0.0.2`로 변경합니다. 같은 버전을 다시 빌드하면 기존에 서명한 SWU를 포함한 출력이 교체됩니다. 보드는 이미지 버전 정책을 적용합니다.

## 6. 배포 준비

번들을 빌드하고 검증하는 것만으로 보드가 변경되지는 않습니다. 배포 전 다음을 확인하세요.

- 새 보드에 플래시할 때는 첫 부팅 접근을 설정하세요. 기본적으로 `root`와 `sima` 계정은 잠겨 있습니다. 업데이트 시 기존 보드의 인증 정보가 유지될 수 있습니다. [보드 접근](palette-image-builder-reference.md#board-access)을 참고하세요.
- 승인된 보드 프로비저닝 절차를 통해 CA를 설정하세요. 기본 보드는 새로 생성한 CA를 자동으로 신뢰하지 않습니다.
- `.swu`는 SWUpdate를 사용하고, `.img.gz`와 필요한 부팅 페이로드는 보드에서 검증된 미디어/복구 절차를 사용하세요.

SSH 업데이트 명령은 [SWU 설치](palette-image-builder-reference.md#installing-an-swu)를 확인하세요. 프로덕션에 사용하기 전에 복구 가능한 개발 보드에서 이미지를 검증하세요.

## 문제 해결

- **루프/device-mapper 접근 불가:** `pib doctor`를 실행하세요. 런처가 필요한 특권을 제공하지만 Linux Docker 호스트가 장치를 지원해야 합니다.
- **x86에서 ARM64 설정 실패:** PIB는 포함된 에뮬레이터를 자동 등록합니다. Linux Docker 엔진이 특권 binfmt 접근을 허용하는지 확인하세요.
- **이미지 빌드 중단:** 먼저 빌드를 중지하고 `pib clean`으로 남은 리소스를 확인한 다음 `pib clean --yes`로 제거하세요. 같은 Docker 호스트의 다른 PIB 프로젝트도 정리 대상에 포함될 수 있습니다.
- **패키지/bootstrap 실패:** `configs/images/mmdebstrap.log`를 확인하세요. 빌드 중 패키지 저장소에 연결할 수 있어야 합니다.
- **새 플랫폼 릴리스:** 해당 릴리스 컨테이너로 새 프로젝트를 초기화하고 기존 CA와 호환되는 패키지 및 사용자 지정을 옮기세요. [업그레이드 참조](palette-image-builder-reference.md#new-platform-release)를 확인하세요.
