# Branch 관측 추출 방법

`branch-observations-1.0`은 기존 분석 결과를 보존하는 추가 관측 계층입니다. 원본 acquisition 순서에서 같은 조건의 연속 run만 만들고, sweep의 turning point를 양쪽 branch에 보존합니다. 서로 떨어진 반복·gate reset을 합치지 않습니다. `original_sweep`은 원래 trace 전체 범위이고 `branch_sweep`은 해당 branch 범위입니다. 비교를 위해 stress 범위를 crop하지 않습니다.

평가점은 원본 exact 점이 우선이며, 하나의 인접 bracket에서 signed 전류를 선형 보간합니다. 누락 행·compliance·segment·acquisition gap을 넘어 보간하지 않습니다. 같은 전압에 다른 전류가 있으면 모호한 값으로 보류합니다. 외삽하지 않습니다.

RR은 `abs(Id(+u))/abs(Id(-u))`로 방향을 고정합니다. 평가 |Vd| 기본값은 0.1/0.5/1/1.5/2입니다. 단위 미확인에서도 같은 전류 채널의 scale이 소거되는 비는 탐색값으로 제공하며 평가 전압의 SI 가정은 별도 제한입니다. 검출한계가 없으면 분모 신뢰도는 미평가이고 bound를 만들지 않습니다. 분모 0은 null입니다. 알려진 floor+근거와 단위가 있을 때만 bound를 계산합니다.

G0는 영전압 근처에서 `I=offset+G0*V` 자유 절편 최소제곱입니다. 반폭 0.025/0.05/0.1과 최소 5개 서로 다른 양·음 전압 점을 사용합니다. 창을 임의 확대하거나 gap을 넘지 않습니다. residual과 창 민감도를 기록합니다. 고유 접촉저항으로 해석하지 않습니다. Secant G는 signed I/V, gds는 실제 좌표 local quadratic의 선형 계수입니다. gds 전체 창 0.2/0.4/0.8, 최소 7점이며 끝점의 부분 창 지원 여부를 따로 남깁니다.

gm도 실제 좌표 local quadratic의 signed 미분입니다. 전체 창 1/2/4 V, 최소 5개 고유 점을 사용하며 peak는 전체 창이 지원되는 내부 점에서만 선택합니다. amplitude·위치·창 민감도·여러 local peak·half-height 폭과 censoring을 기록합니다. 폭 계산에 사용한 원본 점도 남습니다. 이동 평균/재표본화/중복 전압 평균을 하지 않습니다.

최대/최소 |Id|의 비는 Imax/Imin으로 부르고 ON/OFF 상태로 확정하지 않습니다. gate쌍 ±20/±40의 값은 원래 stress 범위를 보존한 해당 branch 안의 관측입니다. Vcc는 단위 근거가 있는 명시 전류 기준 1e-10/1e-9/1e-8 A의 유일한, 주변 최소 5점 단조 교차만 제공합니다. 실제 VT와 구분합니다. 역 log 기울기는 같은 부호·단조·연속 구간, 최소 5점·1 decade에서 평가한 탐색값이며 floor·누설·subthreshold 영역 미확인으로 검증된 SS를 주장하지 않습니다.

Hysteresis는 같은 run에서 turning point를 공유한 인접 forward/reverse branch만 비교합니다. 같은 gate의 signed 전류 차, 같은 전류 기준의 reverse−forward gate 차를 제공합니다. 다른 반복이나 ±20/±40 stress를 crop하여 합치지 않습니다. 독립 반복의 근거가 없으면 CI를 계산하지 않습니다.

누설 ratio는 같은 점의 |Ig/Id|이며 두 전류 채널의 SI 변환 근거가 모두 있어야 단위 확인값입니다. 하나라도 미확인이면 SI scale 가정값으로 남습니다. 최대 |Ig|는 Ig 단위만으로 판정하며 Id나 sweep 전압 단위의 미확인 때문에 보류하지 않습니다. `unit_dependencies`에 각 지표가 실제로 의존하는 채널을 기록합니다. compliance/parse 제외 점은 ratio 추출에서 제외하고, 관측 Ig 최대값은 원본과 point flag를 함께 보존합니다. Ig를 Id에서 빼지 않습니다. 원본 점의 행·셀·전압·전류·unit mapping·제외 flag가 근거 JSON과 CSV에 있습니다.

단위·날짜·광 조건을 위조하지 않고 기존 사용자 override 이력만 읽습니다. filename delay와 Settings의 차이는 나란히 유지합니다. μ·물리 VT·고유 Rc·장벽 높이는 해당 소자 치수·정전용량·모델/온도/측정 근거 없이는 null+이유입니다.

위 창 폭·최소 점 수·criterion은 engineering 기본값입니다. 문헌의 보편적 물리 문턱으로 표현하지 않습니다. [Cheng et al.](https://arxiv.org/pdf/2203.16759)의 조건·sweep·누설·최대/최소 전류 보고 원칙과 [Bennett et al.](https://poplab.stanford.edu/pdfs/Bennett-TransistorsGateDependentRc-npj2d25.pdf)의 gate 의존 접촉저항에 따른 해석 제한을 참고했습니다.
