# 샘플 사용자 지정 이미지 빌드

이 안내에서는 작은 애플리케이션, 설정 파일, 자동 시작 서비스를 포함한 서명된 Modalix 이미지를 만듭니다. 완전한 샘플이 PIB에 포함되어 있어 저장소 복제나 호스트 빌드 도구 설치가 필요하지 않습니다. CI에서도 같은 이미지 명세를 x86과 ARM64에서 테스트합니다.

## 1. PIB 설치 및 확인

sima-cli를 설치하고 Linux 엔진의 Docker를 시작한 다음 실행합니다.

```bash
sima-cli neat install sdk/pib
pib --version
pib doctor
```


현재 터미널에서 `pib`를 찾지 못하면 새 터미널을 여세요. Bash 또는 Zsh에서는 PATH를 즉시 갱신할 수도 있습니다.

```bash
export PATH="$HOME/.local/bin:$PATH"
```


PIB는 네이티브 x86 또는 ARM64 컨테이너를 사용합니다. x86에서는 ARM64 에뮬레이터가 자동 설정됩니다. 이 minimal 이미지 예제에는 특권 Docker 컨테이너와 프로젝트 및 Docker 저장소 각각 10 GiB 이상의 여유 공간이 필요합니다.

Windows 설치는 Linux 컨테이너 모드 Docker와 네이티브 런처를 사용합니다. Windows 설치 프로그램 단위 테스트는 통과했지만 Docker Desktop/WSL2의 전체 이미지 생성은 아직 검증되지 않았습니다. 아래 명령은 Bash 인용 구문을 사용합니다.

## 2. 예제를 프로젝트로 복사

```bash
pib init my-custom-image --example custom-image
cd my-custom-image
```


다음 파일을 사용자 지정합니다.

| 파일 | 용도 |
|---|---|
| `image.yaml` | 이미지 유형, 버전, 패키지, 오버레이, 훅, 서명 설정 |
| `package-root/usr/bin/pib-example-app` | 예제 Debian 패키지가 설치하는 애플리케이션 |
| `package-root/DEBIAN/control` | 패키지 이름, 버전, 아키텍처 |
| `overlay/etc/pib-example.conf` | 이미지에 복사할 애플리케이션 설정 |
| `overlay/etc/systemd/system/pib-example.service` | 서비스 정의 |
| `hooks/enable-example.sh` | 서비스를 활성화하고 빌드 표시 파일을 생성하는 훅 |

컨테이너 안의 Linux 셸을 열려면 실행합니다.

```bash
pib shell
```


프로젝트가 `/workspace`에 마운트됩니다. `exit`로 컴퓨터의 셸에 돌아갑니다. 나머지 명령은 컴퓨터의 프로젝트 디렉터리에서 실행하세요. 각 `pib` 명령이 컨테이너를 자동 시작합니다.

## 3. 개발용 서명 정보 생성

```bash
pib keys init --cn 'My Company Development'
```


CA, SWU 서명 인증서와 개인 키, 사용자 지정 Debian 패키지 서명 정보가 생성됩니다. 설정 후 `keys/ca.key`를 프로젝트 밖의 안전한 위치로 옮기세요. 기존 보드를 업데이트할 때도 같은 CA를 유지합니다. 출하용 이미지에는 조직의 프로덕션 서명 절차를 사용하세요.

## 4. 애플리케이션 패키징 및 서명

PIB 안에서 패키지를 빌드하고 서명 및 검증합니다.

```bash
pib shell -c 'dpkg-deb --root-owner-group --build package-root custom-debs/pib-example-app_1.0.0_all.deb'
pib sign-debs
pib verify-debs
```


샘플은 셸 스크립트이므로 아키텍처 `all`을 사용합니다. 컴파일된 Modalix 애플리케이션은 보통 SDK로 `arm64`용 빌드를 수행해야 합니다. PIB는 ARM64 또는 아키텍처 독립 패키지를 받으며 애플리케이션 소스 코드를 크로스 컴파일하지 않습니다.

## 5. 이미지 명세 확인

예제에는 다음 사용자 지정 설정이 포함됩니다.

```yaml
packages:
  add: [pib-example-app]
  remove: []
overlay: overlay
hooks: [hooks/enable-example.sh]
```


패키지 목록에는 `.deb` 파일명이 아닌 Debian 패키지 이름을 씁니다. 편집기에서 `overlay/etc/pib-example.conf`를 수정하여 설정을 바꿔 보세요. 훅은 패키지 설치 후 샘플 서비스를 활성화합니다.

이미지 버전은 컨테이너 플랫폼 릴리스에 빌드 번호를 붙인 형식이어야 합니다. 예: `3.0.0.1`. 다음 이미지에서는 마지막 숫자를 증가시키세요. 보드는 다운그레이드 금지 정책을 적용합니다.

## 6. 이미지 빌드·서명·검증

```bash
pib build --sign --supplier 'My Company'
pib verify
```


첫 명령은 새 루트 파일시스템을 구성하고, 애플리케이션 설치와 오버레이 및 훅 적용을 수행하며, 배포 아티팩트를 생성하고 SWU를 서명·검증합니다. 두 번째 명령은 프로젝트 기본 CA와 인접 매니페스트를 사용하는 독립 검증을 보여줍니다.

## 7. 출력 찾기

프로젝트의 `out/` 디렉터리를 확인하세요.

| 출력 | 사용 방법 |
|---|---|
| `*.swu` | 실행 중인 보드의 서명된 소프트웨어 업데이트 |
| `*.img.gz` | 초기 프로비저닝 또는 복구용 전체 디스크 이미지 |
| `*.manifest.json` | 설치 패키지 버전, 출처, 빌드 식별 정보 |
| `*.cdx.json` | 소프트웨어 자재 명세서 |
| `SHA256SUMS` | 아티팩트 체크섬 |

SWU와 전체 디스크 이미지는 서로 다른 배포 형식입니다. SWU 설치와 최초 CA 신뢰 설정은 [보드 업데이트 참조](palette-image-builder-reference.md#installing-an-swu)를 따르세요. 전체 디스크 이미지는 Modalix 프로비저닝 절차를 사용합니다. 프로덕션 전에 개발 보드에서 이미지를 검증하세요.

## 8. 샘플을 실제 애플리케이션으로 교체

SDK로 애플리케이션의 ARM64 Debian 패키지를 빌드한 다음 `custom-debs/`에 넣고 `image.yaml`에 패키지 이름을 추가하세요. 설정, 서비스, 훅을 변경한 후 패키지 서명과 이미지 생성을 반복합니다. SDK, PIB, DevKit의 역할은 [SDK 아키텍처 가이드](sdk-architecture.md)를 확인하세요.

## 반복 빌드 가속

PIB는 pigz로 gzip 호환 병렬 압축을 수행합니다. 검증된 패키지 다운로드를 빌드 사이에 재사용하려면 다음과 같이 설정합니다.

```bash
export PIB_DEB_CACHE="$HOME/.cache/sima/pib-debs"
pib build --sign
```


저장소 서명과 패키지 해시는 빌드마다 확인합니다. 웜 캐시도 루트 파일시스템 재사용이나 패키지 설치, 훅, 서명, 검증의 생략을 의미하지 않습니다.
