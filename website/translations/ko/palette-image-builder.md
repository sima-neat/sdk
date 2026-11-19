# 맞춤형 이미지 워크플로

Palette SDK와 함께 사용하는 Palette Image Builder(PIB)로 소프트웨어와 시스템 설정을 맞춤형 Modalix eLxr 이미지로 만듭니다. 이 페이지는 전체 과정을 설명합니다. 패키지, 서비스, 오버레이를 직접 구성하는 절차는 [예제 이미지](palette-image-builder-example.md)를 참조하세요.

## PIB 설치

[sima-cli](https://docs.sima-neat.com/getting-started/installation)를 설치하고 Linux 엔진을 사용하는 Docker를 시작한 후 실행하세요.

```bash
sima-cli neat install sdk/pib
```


설치 프로그램은 호스트에 맞는 x86_64 또는 ARM64 컨테이너를 선택하고 실행기와 PATH를 설정하며 Docker 호스트를 자동으로 확인합니다. PATH가 변경되었다면 새 터미널을 여세요. PIB 실행에 기본 SDK 컨테이너는 필요하지 않습니다.

이미지 생성에는 Docker의 특권 접근, 저장소 연결, 프로젝트 및 Docker 저장 공간이 필요합니다. `minimal`은 10 GiB, `palette`는 20 GiB를 확보하세요. x86에서는 ARM64 에뮬레이션을 자동 설정합니다. 지원 플랫폼, 다른 릴리스 선택, 수동 설치는 [설치 참조](palette-image-builder-reference.md#installation)를 확인하세요.

## 1. 이미지 프로젝트 생성

```bash
pib init my-image --flavor minimal
cd my-image
```


플랫폼 릴리스와 호환되는 종류를 선택하세요. 데스크톱과 더 많은 패키지가 필요하면 `palette`를 사용합니다. `configs/`의 릴리스별 보드 기본값은 선택한 빌더가 제공하므로 일반적으로 변경하지 않습니다. 이후 명령은 프로젝트 디렉터리에서 실행하세요.

## 2. 이미지 내용 정의

| 입력 | 목적 |
|---|---|
| `image.yaml` | 종류, 릴리스, 이미지 버전, 패키지 및 서명 설정 |
| `custom-debs/` | ARM64 또는 아키텍처 독립 Debian 패키지 |
| `overlay/` | 루트 파일 시스템에 복사할 설정 및 파일 |
| `hooks/` | 서비스 활성화 등 패키지 설치 후 변경 |

Palette SDK로 애플리케이션을 빌드하고 모델을 컴파일한 다음 대상에 필요한 파일을 패키징하세요. PIB는 패키지를 조합하며 애플리케이션 소스를 컴파일하지 않습니다. 구성 요소의 역할은 [Palette SDK 시스템 스택](sdk-architecture.md)을 참조하세요.

`image.yaml`에는 `.deb` 파일명 대신 Debian 패키지 이름을 나열합니다. 파일은 오버레이에, 설치 후 변경은 훅에 지정하세요. 패키지, 커널, 훅 규칙은 [사용자 지정 참조](palette-image-builder-reference.md#customization)에 있습니다.

## 3. 서명과 신뢰 준비

개발용 프로젝트 서명 정보를 한 번 생성하세요.

```bash
pib keys init --cn 'My Company Development'
```


설정 후 CA 개인 키를 오프라인으로 보관하세요. 기존 보드를 업데이트할 때 동일한 CA를 유지하고, 출하 이미지에는 조직의 프로덕션 서명 절차를 사용합니다. 외부 키, 인증서 갱신, 빌드와 서명 분리는 [서명 참조](palette-image-builder-reference.md#signing)를 확인하세요.

## 4. 빌드 및 검증

사용자 지정 Debian 패키지가 있다면 이미지 빌드 전에 서명하고 검증하세요.

```bash
pib sign-debs
pib verify-debs
pib build --sign
pib verify
```


빌드는 새 루트 파일 시스템을 만들고 프로젝트 입력을 적용하며 배포 아티팩트를 생성한 뒤 SWU를 서명하고 검증합니다. 결과와 패키지 매니페스트, SBOM, 체크섬은 `out/`에 저장됩니다.

## 5. 배포 및 유지 관리

| 아티팩트 | 배포 목적 |
|---|---|
| 서명된 `.swu` | 실행 중인 보드 업데이트 |
| `.img.gz` | 초기 디스크 프로비저닝 또는 복구 |

배포 전에 보드 접근과 CA 신뢰를 설정하세요. [보드 접근](palette-image-builder-reference.md#board-access) 및 [SWU 설치](palette-image-builder-reference.md#installing-an-swu) 절차를 따르세요. 빌드 성공만으로 보드가 변경되거나 검증되지는 않습니다.

복구 가능한 하드웨어에서 이미지를 검증하고 매니페스트, 체크섬, 서명 정보를 보관하세요. 후속 업데이트에는 이미지 버전을 올립니다. 플랫폼 릴리스를 바꿀 때는 새 프로젝트로 호환되는 입력을 옮기세요. [플랫폼 업그레이드 참조](palette-image-builder-reference.md#new-platform-release)를 확인하세요.

부트 파티션, rootfs 슬롯, 데이터 볼륨 할당은 [미디어 및 파티션 구조](palette-image-builder-reference.md#media-and-partition-layout)를 참조하세요.

## 예제 또는 참조로 계속하기

- [예제 이미지](palette-image-builder-example.md): 포함된 애플리케이션 패키지, 설정, 서비스를 단계별로 빌드합니다.
- [Palette Image Builder 참조](palette-image-builder-reference.md): 명령, 사용자 지정 규칙, 서명, 문제 해결, 보드 작업.
