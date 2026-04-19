*** Settings ***
Documentation       Base page object. Every page object resource imports this
...                 to inherit navigation + generic waits.


*** Keywords ***
Navigate To Path
    [Arguments]    ${path}
    ${base}=    Config.Get Base Url
    Go To    ${base}${path}

Current Path Should Be
    [Arguments]    ${expected}
    ${url}=    Get Location
    Should End With    ${url}    ${expected}

Page Should Be Ready
    [Documentation]    Waits for the document to reach ``complete`` readyState.
    Wait For Condition    return document.readyState == "complete"    timeout=20s
