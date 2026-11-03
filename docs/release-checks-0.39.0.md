# 0.39.0 배포 검사 재선정 근거

기준: 기존 목록 118개 파일, 제품 코드 `1466923`(0.38.1 `c62898fe` 대비 변경).
이 문서는 선택 범위 설명이다. 전체 검사 파일/사례/assertion과 수동 `regression.yml`은 그대로 유지한다.
일반 UI 수정은 이 작업 범위가 아니다. 머리 상태 줄 경고안은 사용자 승인 전 목업만 준비한다.

## 변경 파일과 검사 연결

`packaging/release_checks.json`의 `coverage`가 기계 검증 가능한 연결과 이유다. 아래는 같은 연결의 검토용 표다.

| 변경 파일 또는 의존 공통 계약 | 포함 검사 파일 | 이유 |
| --- | --- | --- |
| `src/mabinogi_addon/autofind_state.py` | `tests/test_autofind_v2.py`, `tests/test_autofind_thread.py` | 발견/활성 분리, 5개 독립 소비자, 확인·취소·대상 변경·재시작·상주 작업자·100% 읽힘·미판독 안내 |
| `src/mabinogi_addon/ui/autofind_runtime.py` | `tests/test_autofind_v2.py`, `tests/test_autofind_thread.py` | 발견/활성 분리, 5개 독립 소비자, 확인·취소·대상 변경·재시작·상주 작업자·100% 읽힘·미판독 안내 |
| `src/mabinogi_addon/autofind_replay.py` | `tests/test_autofind_mvp.py`, `tests/test_autofind_diagnostics.py` | 실제 검출→확인→등록·ZIP 재생·취소/저장 실패 계약 |
| `src/mabinogi_addon/ui/autofind_confirm.py` | `tests/test_autofind_mvp.py`, `tests/test_autofind_diagnostics.py` | 실제 검출→확인→등록·ZIP 재생·취소/저장 실패 계약 |
| `src/mabinogi_addon/setup_state.py` | `tests/test_setup.py`, `tests/test_setup_common_resources.py`, `tests/test_guide_images.py` | 첫 안내 단계·재진입/취소/종료·기존 설정 보존·공유 자원 찾기·안내 자산 |
| `src/mabinogi_addon/ui/setup_flow.py` | `tests/test_setup.py`, `tests/test_setup_common_resources.py`, `tests/test_guide_images.py` | 첫 안내 단계·재진입/취소/종료·기존 설정 보존·공유 자원 찾기·안내 자산 |
| `src/mabinogi_addon/ui/setup_guide.py` | `tests/test_setup.py`, `tests/test_setup_common_resources.py`, `tests/test_guide_images.py` | 첫 안내 단계·재진입/취소/종료·기존 설정 보존·공유 자원 찾기·안내 자산 |
| `src/mabinogi_addon/ui/main_window.py` | `tests/test_home_page.py`, `tests/test_navigation_all_widths.py`, `tests/test_public_release.py`, `tests/test_startup_smoke.py`, `tests/test_game_restart_reset.py` | 홈 이어하기·안내 탐색·공개 사용/권한·최소 기동/종료·게임 재시작 연결 |
| `src/mabinogi_addon/config.py` | `tests/test_config_atomic.py`, `tests/test_config_bundle.py`, `tests/test_feature_release_policy.py` | 원자 저장/손상 복구·백업 가져오기·기존 사용자 기본값 및 1회 이전 보존(setup도 포함) |
| `src/mabinogi_addon/ui/settings_tab.py` | `tests/test_setup.py`, `tests/test_autofind_v2.py` | 안내 다시 보기와 자동 찾기 설정 양방향 동기화 |
| `src/mabinogi_addon/ui/region_registration.py` | `tests/test_region_registration.py`, `tests/test_region_selector_lifecycle.py` | 영역 선택/해제·소비자 연결·취소/종료·등록 요약과 안내 노출 |
| `src/mabinogi_addon/ui/region_section.py` | `tests/test_region_registration.py`, `tests/test_region_selector_lifecycle.py` | 영역 선택/해제·소비자 연결·취소/종료·등록 요약과 안내 노출 |
| `src/mabinogi_addon/ui/buff_tab.py` | `tests/test_status_panel.py`, `tests/test_autofind_v2.py` | 1080 대체 아이콘 열·빈 화면 거부·기존 멤버십/4K 앵커 좌표 및 영역 계약 |
| `src/mabinogi_addon/detect/status_panel.py` | `tests/test_status_panel.py`, `tests/test_autofind_v2.py` | 1080 대체 아이콘 열·빈 화면 거부·기존 멤버십/4K 앵커 좌표 및 영역 계약 |
| `src/mabinogi_addon/detect/halo_timer.py` | `tests/test_halo_timer.py`, `tests/test_halo_autofind.py`, `tests/test_halo_capture.py`, `tests/test_halo_clock.py` | 위치 탐색 15분 초과 허용과 알림 15분 제한 분리·보스 문맥/재동기화 |
| `src/mabinogi_addon/ui/halo_capture_section.py` | `tests/test_halo_timer.py`, `tests/test_halo_autofind.py`, `tests/test_halo_capture.py`, `tests/test_halo_clock.py` | 위치 탐색 15분 초과 허용과 알림 15분 제한 분리·보스 문맥/재동기화 |
| `src/mabinogi_addon/detect/tuarim_reader.py` | `tests/test_tuarim.py`, `tests/test_resource_live_samples.py`, `tests/test_tuarim_native_autofind.py` | 기존 read_percent 원본/실화면/스케일 회귀·read_observation 100%·오인식/재알림 방지 |
| `src/mabinogi_addon/detect/tuarim_small.py` | `tests/test_tuarim.py`, `tests/test_resource_live_samples.py`, `tests/test_tuarim_native_autofind.py` | 기존 read_percent 원본/실화면/스케일 회귀·read_observation 100%·오인식/재알림 방지 |
| `src/mabinogi_addon/ui/dorcha_tab.py` | `tests/test_dorcha_thread.py`, `tests/test_dorcha_autofind.py`, `tests/test_resource_pair.py`, `tests/test_resource_common_settings.py`, `tests/test_resource_integration.py` | 기존 도르카 스레드·두 자원 같은 창 페어링·원자 등록/부분 성공·독립 표시/알림 |
| `src/mabinogi_addon/ui/resource_tab.py` | `tests/test_dorcha_thread.py`, `tests/test_dorcha_autofind.py`, `tests/test_resource_pair.py`, `tests/test_resource_common_settings.py`, `tests/test_resource_integration.py` | 기존 도르카 스레드·두 자원 같은 창 페어링·원자 등록/부분 성공·독립 표시/알림 |
| `src/mabinogi_addon/capture/shared.py` | `tests/test_autofind_v2.py`, `tests/test_boss_tab.py`, `tests/test_halo_capture.py`, `tests/test_blackbox_combat.py`, `tests/test_debuff_auto.py` | 보스 공유 프레임 구독/해제·각 소비자 단독 사용·패턴/헤일로/디버프/전투 녹화 연결 |
| `src/mabinogi_addon/ui/boss_tab.py` | `tests/test_autofind_v2.py`, `tests/test_boss_tab.py`, `tests/test_halo_capture.py`, `tests/test_blackbox_combat.py`, `tests/test_debuff_auto.py` | 보스 공유 프레임 구독/해제·각 소비자 단독 사용·패턴/헤일로/디버프/전투 녹화 연결 |
| `src/mabinogi_addon/ui/debuff_tab.py` | `tests/test_debuff_identity.py`, `tests/test_debuff_auto.py` | 공유 보스 프레임을 사용하는 디버프 신원·자동 판독/오버레이 연결 |
| `src/mabinogi_addon/ui/stat_bars_tab.py` | `tests/test_autofind_v2.py`, `tests/test_region_registration.py`, `tests/test_stat_visibility.py` | 보스전 저체력 소비자 요구·선택/해제·비활성/재개 시 표시 안전성 |
| `src/mabinogi_addon/ui/capture_guard.py` | `tests/test_capture_guard.py`, `tests/test_overlay_capture.py` | 자동 찾기 캡처가 의존하는 우리 창 제외·복원·중첩/종료 계약 |
| `src/mabinogi_addon/ui/overlay_capture.py` | `tests/test_capture_guard.py`, `tests/test_overlay_capture.py` | 자동 찾기 캡처가 의존하는 우리 창 제외·복원·중첩/종료 계약 |
| `src/mabinogi_addon/assets/release_notes.md` | `tests/test_release_notes.py`, `tests/test_release_notes_trigger.py` | 0.39.0 노트 파싱·기존 사용자 새 버전 표시 계약 |
| `packaging/release_checks.json` | `tests/test_release_checks.py` | 버전·선택 경로 유효성·범위 근거와 변경/공통 계약 매핑 검증 |
| `scripts/run_release_checks.py` | `tests/test_release_checks.py` | 버전·선택 경로 유효성·범위 근거와 변경/공통 계약 매핑 검증 |
| `scripts/release_delivery.py` | `tests/test_release_candidate.py`, `tests/test_windows_ci.py`, `tests/test_startup_build.py` | 후보/승인/버전/동일 산출물·Windows 최소 기동/빌드 계약(인프라 변경 없음) |
| `.github/workflows/windows.yml` | `tests/test_release_candidate.py`, `tests/test_windows_ci.py`, `tests/test_startup_build.py` | 후보/승인/버전/동일 산출물·Windows 최소 기동/빌드 계약(인프라 변경 없음) |
| `packaging/build_windows.py` | `tests/test_release_candidate.py`, `tests/test_windows_ci.py`, `tests/test_startup_build.py` | 후보/승인/버전/동일 산출물·Windows 최소 기동/빌드 계약(인프라 변경 없음) |

## 기존 목록에서 제외한 파일

모두 파일과 assertion을 유지하며 로컬 전체 회귀/별도 수동 개발 회귀에서 계속 수집한다.
공유 보스 소비자 연결은 유지하지만 소비자 내부의 변경 없는 모든 기능까지 배포 선행 검사로 누적하지 않는다.

| 검사 파일 | 이번 배포 목록에서 제외한 이유 |
| --- | --- |
| `tests/test_blackbox.py` | 블랙박스 blackbox 내부 기능 미변경. 보스 전투 녹화 소비자 연결은 blackbox_combat/autofind_v2로 검사. |
| `tests/test_blackbox_access.py` | 블랙박스 access 내부 기능 미변경. 보스 전투 녹화 소비자 연결은 blackbox_combat/autofind_v2로 검사. |
| `tests/test_blackbox_audio_codec.py` | 블랙박스 audio_codec 내부 기능 미변경. 보스 전투 녹화 소비자 연결은 blackbox_combat/autofind_v2로 검사. |
| `tests/test_blackbox_bundle.py` | 블랙박스 bundle 내부 기능 미변경. 보스 전투 녹화 소비자 연결은 blackbox_combat/autofind_v2로 검사. |
| `tests/test_blackbox_export.py` | 블랙박스 export 내부 기능 미변경. 보스 전투 녹화 소비자 연결은 blackbox_combat/autofind_v2로 검사. |
| `tests/test_blackbox_lifecycle.py` | 블랙박스 lifecycle 내부 기능 미변경. 보스 전투 녹화 소비자 연결은 blackbox_combat/autofind_v2로 검사. |
| `tests/test_blackbox_producer.py` | 블랙박스 producer 내부 기능 미변경. 보스 전투 녹화 소비자 연결은 blackbox_combat/autofind_v2로 검사. |
| `tests/test_blackbox_queue.py` | 블랙박스 queue 내부 기능 미변경. 보스 전투 녹화 소비자 연결은 blackbox_combat/autofind_v2로 검사. |
| `tests/test_blackbox_runtime.py` | 블랙박스 runtime 내부 기능 미변경. 보스 전투 녹화 소비자 연결은 blackbox_combat/autofind_v2로 검사. |
| `tests/test_blackbox_service.py` | 블랙박스 service 내부 기능 미변경. 보스 전투 녹화 소비자 연결은 blackbox_combat/autofind_v2로 검사. |
| `tests/test_blackbox_session.py` | 블랙박스 session 내부 기능 미변경. 보스 전투 녹화 소비자 연결은 blackbox_combat/autofind_v2로 검사. |
| `tests/test_blackbox_ui_connection.py` | 블랙박스 설정/복구/업데이트/진단 UI는 미변경. 보스 전투 모드 연결은 blackbox_combat와 autofind_v2로 유지. |
| `tests/test_blackbox_window_probe.py` | 블랙박스 window_probe 내부 기능 미변경. 보스 전투 녹화 소비자 연결은 blackbox_combat/autofind_v2로 검사. |
| `tests/test_frame_summary.py` | 블랙박스 프레임 요약 계산 미변경; 공유 보스 캡처 구독은 autofind_v2에서 직접 검사. |
| `tests/test_optimization.py` | 최적화/프로세스/네트워크 optimization 기능 미변경. 새 안내의 해당 화면 진입은 setup/public_release에서 유지. |
| `tests/test_optimization_network.py` | 최적화/프로세스/네트워크 optimization_network 기능 미변경. 새 안내의 해당 화면 진입은 setup/public_release에서 유지. |
| `tests/test_optimization_contract.py` | 최적화/프로세스/네트워크 optimization_contract 기능 미변경. 새 안내의 해당 화면 진입은 setup/public_release에서 유지. |
| `tests/test_optimization_ui.py` | 최적화/프로세스/네트워크 optimization_ui 기능 미변경. 새 안내의 해당 화면 진입은 setup/public_release에서 유지. |
| `tests/test_blackbox_hotkey.py` | 블랙박스 hotkey 내부 기능 미변경. 보스 전투 녹화 소비자 연결은 blackbox_combat/autofind_v2로 검사. |
| `tests/test_autostart.py` | 기존 autostart 기능 미변경; 자동 찾기/첫 안내의 직접 변경 또는 필수 공통 계약에 해당하지 않아 전체 회귀에 유지. |
| `tests/test_updater_relaunch_env.py` | 기존 updater_relaunch_env 기능 미변경; 자동 찾기/첫 안내의 직접 변경 또는 필수 공통 계약에 해당하지 않아 전체 회귀에 유지. |
| `tests/test_manual_update_progress.py` | 기존 manual_update_progress 기능 미변경; 자동 찾기/첫 안내의 직접 변경 또는 필수 공통 계약에 해당하지 않아 전체 회귀에 유지. |
| `tests/test_overlay_metrics.py` | 기존 overlay_metrics 기능 미변경; 자동 찾기/첫 안내의 직접 변경 또는 필수 공통 계약에 해당하지 않아 전체 회귀에 유지. |
| `tests/test_blackbox_stream.py` | 블랙박스 stream 내부 기능 미변경. 보스 전투 녹화 소비자 연결은 blackbox_combat/autofind_v2로 검사. |
| `tests/test_blackbox_public.py` | 블랙박스 public 내부 기능 미변경. 보스 전투 녹화 소비자 연결은 blackbox_combat/autofind_v2로 검사. |
| `tests/test_log_throttle.py` | 기존 log_throttle 기능 미변경; 자동 찾기/첫 안내의 직접 변경 또는 필수 공통 계약에 해당하지 않아 전체 회귀에 유지. |
| `tests/test_process_priority.py` | 최적화/프로세스/네트워크 process_priority 기능 미변경. 새 안내의 해당 화면 진입은 setup/public_release에서 유지. |
| `tests/test_optimization_priority.py` | 최적화/프로세스/네트워크 optimization_priority 기능 미변경. 새 안내의 해당 화면 진입은 setup/public_release에서 유지. |
| `tests/test_process_threads.py` | 최적화/프로세스/네트워크 process_threads 기능 미변경. 새 안내의 해당 화면 진입은 setup/public_release에서 유지. |
| `tests/test_blackbox_cpu.py` | 블랙박스 cpu 내부 기능 미변경. 보스 전투 녹화 소비자 연결은 blackbox_combat/autofind_v2로 검사. |
| `tests/test_access_cache.py` | 최적화/프로세스/네트워크 access_cache 기능 미변경. 새 안내의 해당 화면 진입은 setup/public_release에서 유지. |
| `tests/test_optimization_auto.py` | 최적화/프로세스/네트워크 optimization_auto 기능 미변경. 새 안내의 해당 화면 진입은 setup/public_release에서 유지. |
| `tests/test_blackbox_resume.py` | 블랙박스 resume 내부 기능 미변경. 보스 전투 녹화 소비자 연결은 blackbox_combat/autofind_v2로 검사. |
| `tests/test_cpu_layouts.py` | 최적화/프로세스/네트워크 cpu_layouts 기능 미변경. 새 안내의 해당 화면 진입은 setup/public_release에서 유지. |
| `tests/test_optimization_recommend.py` | 최적화/프로세스/네트워크 optimization_recommend 기능 미변경. 새 안내의 해당 화면 진입은 setup/public_release에서 유지. |
| `tests/test_optimization_public.py` | 최적화/프로세스/네트워크 optimization_public 기능 미변경. 새 안내의 해당 화면 진입은 setup/public_release에서 유지. |
| `tests/test_graphics_efficiency.py` | 최적화/프로세스/네트워크 graphics_efficiency 기능 미변경. 새 안내의 해당 화면 진입은 setup/public_release에서 유지. |
| `tests/test_debuff_native_icons.py` | 기존 debuff_native_icons 검출/표시 규칙 미변경. 변경된 탐색·등록·공유 입력 경계는 autofind_mvp/autofind_v2 및 해당 판독 검사로 유지. |
| `tests/test_crescendo_native.py` | 기존 crescendo_native 검출/표시 규칙 미변경. 변경된 탐색·등록·공유 입력 경계는 autofind_mvp/autofind_v2 및 해당 판독 검사로 유지. |
| `tests/test_debuff_engine.py` | 디버프 엔진 내부 시간/점수 정책 미변경. 변경된 공유 입력 연결은 debuff_auto/identity와 autofind_v2에서 유지. |
| `tests/test_debuff_added_defaults.py` | 기존 debuff_added_defaults 검출/표시 규칙 미변경. 변경된 탐색·등록·공유 입력 경계는 autofind_mvp/autofind_v2 및 해당 판독 검사로 유지. |
| `tests/test_debuff_icon_migration.py` | 기존 debuff_icon_migration 검출/표시 규칙 미변경. 변경된 탐색·등록·공유 입력 경계는 autofind_mvp/autofind_v2 및 해당 판독 검사로 유지. |
| `tests/test_status_icons.py` | 기존 status_icons 검출/표시 규칙 미변경. 변경된 탐색·등록·공유 입력 경계는 autofind_mvp/autofind_v2 및 해당 판독 검사로 유지. |
| `tests/test_tracker_layout.py` | 기존 tracker_layout 검출/표시 규칙 미변경. 변경된 탐색·등록·공유 입력 경계는 autofind_mvp/autofind_v2 및 해당 판독 검사로 유지. |
| `tests/test_tray_status.py` | 기존 tray_status 기능 미변경; 자동 찾기/첫 안내의 직접 변경 또는 필수 공통 계약에 해당하지 않아 전체 회귀에 유지. |
| `tests/test_dorcha_inquiry.py` | 도르카 진단 ZIP/문의 UI 미변경. 작업자/재탐색/등록은 dorcha_thread/dorcha_autofind/resource_common_settings로 유지. |
| `tests/test_buff_favorites.py` | 기존 buff_favorites 검출/표시 규칙 미변경. 변경된 탐색·등록·공유 입력 경계는 autofind_mvp/autofind_v2 및 해당 판독 검사로 유지. |
| `tests/test_buff_favorites_ui.py` | 기존 buff_favorites_ui 검출/표시 규칙 미변경. 변경된 탐색·등록·공유 입력 경계는 autofind_mvp/autofind_v2 및 해당 판독 검사로 유지. |
| `tests/test_settings_grouping.py` | 설정 전체 묶음 레이아웃 미변경. 추가된 자동 찾기 설정 동기화/안내 다시 보기는 autofind_v2/setup에서 검사. |
| `tests/test_interaction_polish.py` | 기존 interaction_polish 공통 화면 스타일/조작 정책 미변경. 변경 안내와 영역 등록 화면은 setup/region_registration/navigation_all_widths에서 검사. |
| `tests/test_custom_autosave.py` | 이번 자동 찾기 변경과 독립적인 custom_autosave 기능 미변경. |
| `tests/test_calculator_result_state.py` | 이번 자동 찾기 변경과 독립적인 calculator_result_state 기능 미변경. |
| `tests/test_wrapping_controls.py` | 기존 wrapping_controls 공통 화면 스타일/조작 정책 미변경. 변경 안내와 영역 등록 화면은 setup/region_registration/navigation_all_widths에서 검사. |
| `tests/test_interaction_consistency.py` | 기존 interaction_consistency 공통 화면 스타일/조작 정책 미변경. 변경 안내와 영역 등록 화면은 setup/region_registration/navigation_all_widths에서 검사. |
| `tests/test_creator_dialogue.py` | 기존 creator_dialogue 공통 화면 스타일/조작 정책 미변경. 변경 안내와 영역 등록 화면은 setup/region_registration/navigation_all_widths에서 검사. |
| `tests/test_screen_polish.py` | 기존 screen_polish 공통 화면 스타일/조작 정책 미변경. 변경 안내와 영역 등록 화면은 setup/region_registration/navigation_all_widths에서 검사. |
| `tests/test_color_switch_polish.py` | 0.39.0 테스트의 안내 생성자 호출만 호환 수정. 기존 색·스위치/문구 광범위 검사는 전체 회귀에 유지; 새 안내 단계/폭은 setup/navigation_all_widths로 검사. |
| `tests/test_dungeon_cost.py` | 이번 자동 찾기 변경과 독립적인 dungeon_cost 기능 미변경. |
| `tests/test_theme_colors.py` | 기존 theme_colors 공통 화면 스타일/조작 정책 미변경. 변경 안내와 영역 등록 화면은 setup/region_registration/navigation_all_widths에서 검사. |
| `tests/test_theme_personalization.py` | 기존 theme_personalization 공통 화면 스타일/조작 정책 미변경. 변경 안내와 영역 등록 화면은 setup/region_registration/navigation_all_widths에서 검사. |
| `tests/test_dialog_buttons.py` | 기존 dialog_buttons 공통 화면 스타일/조작 정책 미변경. 변경 안내와 영역 등록 화면은 setup/region_registration/navigation_all_widths에서 검사. |
| `tests/test_debuff_wireweb.py` | 기존 debuff_wireweb 검출/표시 규칙 미변경. 변경된 탐색·등록·공유 입력 경계는 autofind_mvp/autofind_v2 및 해당 판독 검사로 유지. |
| `tests/test_skillbar_mask.py` | 기존 skillbar_mask 검출/표시 규칙 미변경. 변경된 탐색·등록·공유 입력 경계는 autofind_mvp/autofind_v2 및 해당 판독 검사로 유지. |
| `tests/test_time_4k_render.py` | 기존 time_4k_render 검출/표시 규칙 미변경. 변경된 탐색·등록·공유 입력 경계는 autofind_mvp/autofind_v2 및 해당 판독 검사로 유지. |
| `tests/test_boss_bar_4k.py` | 기존 boss_bar_4k 검출/표시 규칙 미변경. 변경된 탐색·등록·공유 입력 경계는 autofind_mvp/autofind_v2 및 해당 판독 검사로 유지. |
| `tests/test_resource_4k.py` | 기존 4K 자원 장식/확대 표시 정책 미변경. 수정된 투아림 판독은 tuarim/resource_live_samples/tuarim_native_autofind의 실제·확대 원본으로 검사. |
| `tests/test_skillbar_4k.py` | 기존 skillbar_4k 검출/표시 규칙 미변경. 변경된 탐색·등록·공유 입력 경계는 autofind_mvp/autofind_v2 및 해당 판독 검사로 유지. |
| `tests/test_party_keywords_clean.py` | 이번 자동 찾기 변경과 독립적인 party_keywords_clean 기능 미변경. |
| `tests/test_buff_opacity_reorder.py` | 기존 buff_opacity_reorder 검출/표시 규칙 미변경. 변경된 탐색·등록·공유 입력 경계는 autofind_mvp/autofind_v2 및 해당 판독 검사로 유지. |
| `tests/test_boss_name_4k.py` | 기존 boss_name_4k 검출/표시 규칙 미변경. 변경된 탐색·등록·공유 입력 경계는 autofind_mvp/autofind_v2 및 해당 판독 검사로 유지. |
| `tests/test_boss_name_shape.py` | 기존 boss_name_shape 검출/표시 규칙 미변경. 변경된 탐색·등록·공유 입력 경계는 autofind_mvp/autofind_v2 및 해당 판독 검사로 유지. |
| `tests/test_favorites_windowed.py` | 기존 favorites_windowed 검출/표시 규칙 미변경. 변경된 탐색·등록·공유 입력 경계는 autofind_mvp/autofind_v2 및 해당 판독 검사로 유지. |
| `tests/test_theme_banner_polish.py` | 기존 theme_banner_polish 공통 화면 스타일/조작 정책 미변경. 변경 안내와 영역 등록 화면은 setup/region_registration/navigation_all_widths에서 검사. |
| `tests/test_lock_row_wide_spin.py` | 기존 lock_row_wide_spin 공통 화면 스타일/조작 정책 미변경. 변경 안내와 영역 등록 화면은 setup/region_registration/navigation_all_widths에서 검사. |
| `tests/test_boss_bar_small_screen.py` | 기존 boss_bar_small_screen 검출/표시 규칙 미변경. 변경된 탐색·등록·공유 입력 경계는 autofind_mvp/autofind_v2 및 해당 판독 검사로 유지. |
| `tests/test_buff_hidden_kept.py` | 기존 buff_hidden_kept 검출/표시 규칙 미변경. 변경된 탐색·등록·공유 입력 경계는 autofind_mvp/autofind_v2 및 해당 판독 검사로 유지. |
| `tests/test_overlay_window_visible.py` | 전체 오버레이 창 노출 정책 미변경. 변경된 보스 5개 소비자의 독립 출력은 autofind_v2, 자원/체력바 표시 회복은 resource_integration/stat_visibility에서 유지. |
| `tests/test_buff_favorites_public.py` | 기존 buff_favorites_public 검출/표시 규칙 미변경. 변경된 탐색·등록·공유 입력 경계는 autofind_mvp/autofind_v2 및 해당 판독 검사로 유지. |
| `tests/test_boss_brontanas.py` | 기존 boss_brontanas 검출/표시 규칙 미변경. 변경된 탐색·등록·공유 입력 경계는 autofind_mvp/autofind_v2 및 해당 판독 검사로 유지. |
| `tests/test_buff_4k_icons.py` | 4K 버프 아이콘 구제/트래커 유지 정책 자체는 미변경. 변경된 상태 목록 앵커의 기존 4K 좌표/범위는 status_panel, 1080 대체 아이콘은 autofind_v2에서 유지. |
| `tests/test_fastping_game_running.py` | 최적화/프로세스/네트워크 fastping_game_running 기능 미변경. 새 안내의 해당 화면 진입은 setup/public_release에서 유지. |
| `tests/test_sketch_chat.py` | 이번 자동 찾기 변경과 독립적인 sketch_chat 기능 미변경. |
| `tests/test_skillbar_testers.py` | 기존 skillbar_testers 검출/표시 규칙 미변경. 변경된 탐색·등록·공유 입력 경계는 autofind_mvp/autofind_v2 및 해당 판독 검사로 유지. |
| `tests/test_fastping_kept.py` | 최적화/프로세스/네트워크 fastping_kept 기능 미변경. 새 안내의 해당 화면 진입은 setup/public_release에서 유지. |
| `tests/test_cursor_fx.py` | 이번 자동 찾기 변경과 독립적인 cursor_fx 기능 미변경. |
| `tests/test_skillbar_chunk_snap.py` | 기존 skillbar_chunk_snap 검출/표시 규칙 미변경. 변경된 탐색·등록·공유 입력 경계는 autofind_mvp/autofind_v2 및 해당 판독 검사로 유지. |
| `tests/test_alert_volume.py` | 기존 alert_volume 기능 미변경; 자동 찾기/첫 안내의 직접 변경 또는 필수 공통 계약에 해당하지 않아 전체 회귀에 유지. |
| `tests/test_cursor_front.py` | 이번 자동 찾기 변경과 독립적인 cursor_front 기능 미변경. |

## 측정과 한계

전후 같은 Linux 컨테이너·Python/의존성·offscreen·pytest `-n 2 -q --maxfail=3 -m "not windows_integration" --durations=15`로 순차 측정한다.
입력/검출 코드와 원본 자료는 동일하며 선택 목록과 목록 계약 검사만 변경한다. 두 실행 사이에 다른 테스트/렌더를 겹쳐 돌리지 않는다.
pytest 실행을 바깥 monotonic 시계로 잰 시간과 pytest 로그 시간을 함께 기록한다. OS 파일 캐시를 강제로 비우지 않은 단일 전후 측정이므로 순서/러너 부하 효과를 배제할 수 없다.
새로 필요한 판독/배포 계약 검사를 포함하므로 단순히 기존 목록의 부분집합만 실행하는 축소가 아니다.
Windows Actions 시간·최소 기동·실제 exe 빌드는 이번 로컬 측정에서 재실행하지 않으며 5분 달성을 보장하지 않는다.

재현 시 기존 목록은 `git show 1466923:packaging/release_checks.json`의 `tests`, 새 목록은 현재 파일의 `tests`를 읽어
같은 인자를 붙여 순차 실행한다. `--junitxml` 출력 경로만 전후 다르게 지정했다. 배포 감독기의 780초 상한이나
Windows/게시 단계까지 측정한 결과는 아니다. 환경은 Python 3.12.14, Linux x86_64, CPU quota 4 cores,
기존 uv.lock/.venv이며 워커 수는 모두 2다. 표본 렌더는 두 검사 실행 사이에 끝냈다.

### 2026-11-03 로컬 측정 결과

| 목록 | 파일 | 실행 사례 | 결과 | pytest 시간 | 바깥 경과 시간 |
| --- | ---: | ---: | --- | ---: | ---: |
| 변경 전 `1466923` | 118 | 2697 | 2326 passed / 371 skipped | 615.04초 | 615.43초 |
| 재선정 | 43 | 1196 | 1196 passed / 0 skipped | 226.82초 | 227.09초 |

88개 파일을 목록에서 제외하고 빠져 있던 공통 계약/실화면 검사 13개를 추가했다. net 75개 감소이며
새 목록이 기존 목록의 단순 부분집합은 아니다. 경과 시간은 388.34초(6분28초), 약63.1% 감소했다.
이전 조사 2687개와 달리 현재 기준은 후속 미판독 안내 회귀10건이 추가된 2697개다.
0.38.1 실제 Actions의 목록은 107개이며, 118개는 0.39.0 개발 목록을 뜻한다.
전체 회귀4359개 사례의 수집을 확인했으며 실행 통과로 보고하지 않는다. 선택 목록에서 제외한 88개 파일도 수집에 남아 있다.
새 목록의 주요 잔여 비용은 투아림 원본 fixture 준비(개별 setup 약12초), 안내 ZIP 재생(약9초),
자동 찾기 실제 원본 탐색(개별 약3~5초)이다. 이번에는 fixture/검출 코드/worker 수를 변경하지 않았다.
검증 로그·XML은 `/tmp/release-selection-timing/`에 보관했다. Windows CI·전체 배포 시간은 미측정이다.
