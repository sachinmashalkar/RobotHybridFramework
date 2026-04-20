*** Settings ***
Documentation       Example suite showing how to attach to a Chromium-based desktop app
...                 (.exe exposing --remote-debugging-port=9222) via CDP.
...
...                 Tagged `desktop` and `manual` so it is excluded from the default
...                 CI UI/API runs; keyword resolution is still covered by the dry-run
...                 job.

Resource            ../../resources/common/imports.resource

Suite Teardown      CdpConnect.Detach From CDP App    stop_app=False

Test Tags           desktop    cdp    manual


*** Variables ***
${APP_PATH}             ${EMPTY}    # e.g. C:\\Program Files\\MyApp\\MyApp.exe
${DEBUGGER_ADDRESS}     127.0.0.1:9222
${TARGET_HINT}          ${EMPTY}    # e.g. app://main


*** Test Cases ***
Attach To Running Chromium App
    [Documentation]    App is already running with --remote-debugging-port=9222.
    [Tags]    attach
    CdpConnect.Connect To CDP App
    ...    debugger_address=${DEBUGGER_ADDRESS}
    ...    target_url_contains=${TARGET_HINT}
    Wait Until Keyword Succeeds    30x    1s    SeleniumLibrary.Get Location

Launch And Attach To Chromium App
    [Documentation]    Robot Framework owns the app lifecycle.
    ...    Provide APP_PATH via --variable APP_PATH:"C:\\path\\to\\app.exe".
    [Tags]    launch
    Skip If    '${APP_PATH}' == '${EMPTY}'    APP_PATH not provided
    CdpConnect.Connect To CDP App
    ...    app_path=${APP_PATH}
    ...    debugger_address=${DEBUGGER_ADDRESS}
    ...    startup_timeout=90
    ...    target_url_contains=${TARGET_HINT}
    Wait Until Keyword Succeeds    30x    1s    SeleniumLibrary.Get Location
