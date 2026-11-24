# Palette SDK 시스템 스택

Palette SDK는 Modalix용 소프트웨어 개발 도구를 제공합니다. Palette Image Builder(PIB)는 그 소프트웨어를 사용자 지정 eLxr 운영체제 이미지로 구성합니다. 두 컨테이너는 독립적입니다. 애플리케이션 개발에는 SDK를, 디바이스 이미지 사용자 지정에는 PIB를 사용하세요.

이 가이드는 이미지 패키징과 하위 소프트웨어를 다루는 시스템 엔지니어를 위한 문서입니다. 애플리케이션 API와 개발 절차는 [developer.sima.ai/software](https://developer.sima.ai/software)를 참고하세요.

SDK 설정은 호환성 카탈로그에 따라 버전이 맞는 **Model Compiler 확장 기능**도 설치합니다. 필요하지 않으면 건너뛸 수 있습니다. 확장 기능은 모델 아티팩트를 컴파일하고 SDK 도구는 이를 사용하는 애플리케이션을 빌드하며, PIB는 배포할 소프트웨어를 시스템 이미지로 패키징합니다.

[![Palette SDK 시스템 스택: 개발 도구와 Model Compiler 확장 기능의 소프트웨어를 별도의 PIB가 Modalix DevKit 이미지로 패키징합니다.](../images/palette-sdk-system-stack.svg#gh-light-mode-only)](../images/palette-sdk-system-stack.svg)

[![Palette SDK 시스템 스택: 개발 도구와 Model Compiler 확장 기능의 소프트웨어를 별도의 PIB가 Modalix DevKit 이미지로 패키징합니다.](../images/palette-sdk-system-stack-dark.svg#gh-dark-mode-only)](../images/palette-sdk-system-stack-dark.svg)

## 각 구성 요소의 실행 위치

| 구성 요소 | 실행 위치 | 역할 |
|---|---|---|
| sima-cli | 사용자 컴퓨터 | 패키지 설치, 개발 환경 시작 및 설정 |
| Palette SDK 컨테이너 | 사용자 컴퓨터의 Docker | ARM64 sysroot를 대상으로 크로스 컴파일하고 개발 도구 제공 |
| Model Compiler 확장 기능 | SDK 설정 중 설치되는 개발 환경 | Modalix 가속을 위한 모델 컴파일 |
| PIB 컨테이너 | 사용자 컴퓨터의 Docker | 이미지 명세에 따라 루트 파일시스템, 패키지, 디스크 이미지, 서명된 SWU 생성 |
| Modalix DevKit | 대상 디바이스 | ARM64 애플리케이션과 설치된 eLxr 이미지 실행 |

SDK와 PIB 모두 네이티브 x86 및 ARM64 컨테이너를 제공합니다. Docker가 호스트에 맞는 변형을 선택합니다. 대상 애플리케이션과 디바이스 이미지는 ARM64입니다. x86 호스트에서 이미지를 구성할 때 PIB는 ARM64 에뮬레이션을 자동 사용합니다.

## SDK 개발 환경 열기

SDK를 설치하고 개발 환경을 설정합니다.

```bash
sima-cli neat install sdk
sima-cli sdk setup
sima-cli sdk neat
```


설정할 때 DevKit을 페어링하려면 주소를 지정합니다.

```bash
sima-cli sdk setup --devkit 192.0.2.10
```


예제 주소를 실제 DevKit 주소로 바꾸세요. 소프트웨어 빌드에 페어링이 필수는 아니지만 하드웨어 배포와 테스트에 유용합니다.

SDK에는 크로스 툴체인, 대상 sysroot, 헤더, 라이브러리, 개발 도우미가 포함됩니다. 작업 공간은 컨테이너의 `/workspace`에 마운트되므로 컴퓨터에서 파일을 편집하고 SDK 안에서 빌드할 수 있습니다.

## 소프트웨어가 장치에 배포되는 과정

SDK 도구로 Modalix ARM64 sysroot에 맞춰 애플리케이션을 빌드합니다. Model Compiler 확장 기능은 애플리케이션이 사용할 컴파일된 모델 아티팩트를 만듭니다. 애플리케이션, 모델 자산, 필요한 파일은 아키텍처 `arm64`인 Debian 패키지로 구성하세요. 아키텍처 독립 스크립트는 `all`을 사용할 수 있습니다.

PIB는 패키지와 이미지 사양, 설정 오버레이, 훅, 서명 정보를 입력으로 사용합니다. 업데이트용 서명된 `.swu`와 초기 프로비저닝 또는 복구용 `.img.gz`를 생성합니다. 애플리케이션 컨테이너만 빌드해서는 이러한 시스템 이미지 아티팩트가 생성되지 않습니다. PIB는 SDK 컨테이너와 독립적으로 실행할 수 있습니다.

전체 과정은 [맞춤형 이미지 워크플로](palette-image-builder.md), 완전한 예제 절차는 [예제 이미지](palette-image-builder-example.md)를 참조하세요.

## 툴체인·이미지·보드 버전 맞추기

컨테이너의 플랫폼 릴리스가 호환되는 이미지 입력을 결정합니다. PIB는 다른 플랫폼 릴리스용 프로젝트를 거부합니다. 이미지 버전에는 `3.0.0.1`처럼 숫자 빌드 번호가 추가되며 업데이트 정책에 사용됩니다.

릴리스마다 빌드 매니페스트, SBOM, 체크섬, 서명 정보를 보관하세요. 출하한 내용을 식별하고 같은 신뢰 CA로 후속 업데이트를 제공하는 데 필요합니다. 공개 빌더 컨테이너에는 서명 키가 포함되지 않습니다.

## 다음 단계 선택

- 첫 이미지는 [맞춤형 이미지 워크플로](palette-image-builder.md)를 따라 만드세요.
- 동작하는 애플리케이션 예제는 [샘플 안내](palette-image-builder-example.md)를 확인하세요.
- 사용자 지정 커널, 외부 서명, 보드 업데이트는 [PIB 참조](palette-image-builder-reference.md)를 확인하세요.
