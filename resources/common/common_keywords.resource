*** Settings ***
Documentation       Shared setup/teardown + wait/assert helpers used across suites.


*** Keywords ***
Begin Ui Test
    [Documentation]    Standard setup for UI suites. Opens the configured browser
    ...    on the environment base URL.
    [Arguments]    ${browser}=${EMPTY}
    Browser.Open Configured Browser    browser=${browser}
    Set Selenium Speed    0s

End Ui Test
    [Documentation]    Standard teardown. Closes all browsers even on failure
    ...    so subsequent tests start clean.
    Run Keyword If Test Failed    Capture Page Screenshot
    Close All Browsers

Begin Api Suite
    [Documentation]    Initialises the API client against the current environment.
    ${base}=    Config.Get Api Base Url
    API.Set Base Url    ${base}
    Create Session    api    ${base}    verify=True

Wait And Click
    [Arguments]    ${locator}    ${timeout}=10s
    Wait Until Element Is Visible    ${locator}    timeout=${timeout}
    Wait Until Element Is Enabled    ${locator}    timeout=${timeout}
    Click Element    ${locator}

Wait And Input
    [Arguments]    ${locator}    ${text}    ${timeout}=10s
    Wait Until Element Is Visible    ${locator}    timeout=${timeout}
    Clear Element Text    ${locator}
    Input Text    ${locator}    ${text}

Element Should Contain Text
    [Arguments]    ${locator}    ${expected}
    Wait Until Element Is Visible    ${locator}
    ${text}=    Get Text    ${locator}
    Should Contain    ${text}    ${expected}

Take Debug Screenshot
    [Arguments]    ${name}=debug
    ${stamp}=    Utils.Now Iso
    ${safe}=    Replace String Using Regexp    ${stamp}    [:.]    -
    Capture Page Screenshot    filename=${name}_${safe}.png
