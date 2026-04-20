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
${TARGET_HINT}          ${EMPTY}    # e.g. app://main or https://app.local
${BROWSER_KIND}         chrome    # set to "edge" for Edge/WebView2 apps
${DRIVER_PATH}          ${EMPTY}    # e.g. C:\\Tools\\msedgedriver-147\\msedgedriver.exe


*** Test Cases ***
Attach To Running Chromium App
    [Documentation]    App is already running with --remote-debugging-port=9222.
    ...    If the loading splash never finishes, pass TARGET_HINT so the
    ...    connector waits for the real window BEFORE attaching chromedriver.
    ...    For Microsoft Edge / WebView2 apps set BROWSER_KIND=edge and
    ...    DRIVER_PATH to a matching msedgedriver.exe.
    [Tags]    attach
    CdpConnect.Connect To CDP App
    ...    debugger_address=${DEBUGGER_ADDRESS}
    ...    browser=${BROWSER_KIND}
    ...    chromedriver_path=${DRIVER_PATH}
    ...    wait_for_target_contains=${TARGET_HINT}
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
    ...    browser=${BROWSER_KIND}
    ...    chromedriver_path=${DRIVER_PATH}
    ...    startup_timeout=90
    ...    wait_for_target_contains=${TARGET_HINT}
    ...    target_url_contains=${TARGET_HINT}
    Wait Until Keyword Succeeds    30x    1s    SeleniumLibrary.Get Location

Diagnose Cdp Attach
    [Documentation]    Non-attaching diagnostic: prints /json targets.
    ...    Run this first when the loading screen never renders to see
    ...    which targets the app is exposing.
    [Tags]    diagnose
    ${ready}=    CdpConnect.Cdp Is Ready    timeout=5
    Should Be True    ${ready}    CDP endpoint not reachable at ${DEBUGGER_ADDRESS}
    ${targets}=    CdpConnect.List Cdp Targets
    Log    CDP targets: ${targets}    level=WARN
    FOR    ${t}    IN    @{targets}
        Log    ${t}    level=WARN
    END
