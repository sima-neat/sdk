# 하위 시스템 소프트웨어 작업

Modalix 이미지용 BSP 소프트웨어를 준비하는 시스템 엔지니어를 위한 가이드입니다. Palette SDK 툴체인으로 커널과 디바이스 트리를 다루고, PIB로 릴리스와 호환되는 패키지를 이미지에 구성합니다. 애플리케이션 API와 개발 튜토리얼은 [developer.sima.ai/software](https://developer.sima.ai/software)를 참고하세요.

## 호환되는 BSP 릴리스로 시작

대상 플랫폼 릴리스와 일치하는 공급업체 소스 리비전과 설정을 사용하세요. 저장소의 기본 브랜치가 유지 관리 중인 이미지의 소스와 같다는 보장은 없습니다. 소스 리비전, 설정 변경, 패키지 버전을 릴리스 기록에 남깁니다.

아래 빌드 명령은 ARM64 크로스 툴체인 환경이 설정된 Palette SDK 컨테이너에서 실행합니다. 소스를 가져온 후 설정 및 빌드 전에 적절한 릴리스 리비전을 선택하세요.

## 커널 설정 및 빌드

```bash
git clone https://github.com/SiMa-ai/simaai-linux.git
cd simaai-linux
make ARCH=arm64 simaai_modalix_defconfig
make all -j8 ARCH=arm64 LOCALVERSION="-modalix" DTC_FLAGS=-@
```


커널 이미지는 `arch/arm64/boot/Image`에 생성됩니다. 플랫폼 디바이스 트리는 `arch/arm64/boot/dts/simaai/` 아래에 있습니다. 사용한 설정과 소스 리비전을 기록하세요.

이 파일은 빌드 아티팩트이며 완전한 PIB 호환 커널 패키지는 아닙니다. 필요한 부팅 파일, 패키지 스크립트, 릴리스 통합을 유지하려면 플랫폼이 지원하는 Debian 패키징 절차를 사용하세요.

## 디바이스 트리 오버레이 컴파일

```bash
dtc -@ -I dts -O dtb -o imx415.dtbo imx415.dtso
```


예제 파일명을 실제 오버레이 이름으로 바꾸세요. 개발 보드에서 하드웨어 바인딩과 주변 장치 동작을 검증합니다. 해당 플랫폼 릴리스가 지원하는 부팅 설정에 따라 패키징하거나 설치하세요. `.dtbo`를 복사하는 것만으로 자동 활성화되지는 않습니다.

## 부팅 체인 경계 이해

이미지의 커널, U-Boot, ATF, tRoot 구성 요소는 서로 호환되어야 합니다. 현재 PIB 흐름에서 사용자 지정 커널은 릴리스 커널 패키지 이름을 유지하고 설치된 유일한 커널이어야 합니다. 이름은 `configs/images/image-params.yaml`에서 확인하세요.

PIB는 tRoot, ATF, U-Boot의 로컬 교체 패키지를 거부합니다. 이미지의 U-Boot는 `fip.bin`에 포함된 복사본과 일치해야 합니다. `u-boot.bin` 빌드는 부팅 펌웨어를 덮어쓸 권한이나 지원되는 절차를 의미하지 않습니다. 부팅 체인 변경은 플랫폼 공급업체의 복구 및 서명 절차에 따라 조율하세요.

`securepalette`는 추가 커널 FIT 서명 검사를 수행하며 출하용에는 프로덕션 서명된 부팅 패키지가 필요합니다. 보안 부팅의 하드웨어 동작은 minimal 이미지 CI 검증과 별도로 확인해야 합니다.

## PIB로 시스템 변경 패키징

릴리스와 호환되는 ARM64 Debian 패키지를 `custom-debs/`에 넣고 패키지 서명 정보로 서명한 뒤 이미지를 빌드합니다.

```bash
pib sign-debs
pib verify-debs
pib build --sign
pib verify
```


`image.yaml`에는 추가 패키지 이름을, `overlay/`에는 설정을 정의합니다. 서비스 활성화 등 최종 변경에는 설치 후 훅을 사용하세요. 커널 및 패키지 규칙은 [PIB 참조](palette-image-builder-reference.md#customization)에 설명되어 있습니다.

매니페스트와 체크섬을 보관하고 복구 가능한 개발 보드에서 결과 이미지를 테스트하세요. 변경 사항의 영향을 받는 주변 장치와 업데이트/롤백 동작을 검증합니다. 아티팩트 빌드 성공만으로 하드웨어 호환성이 확인되지는 않습니다.
