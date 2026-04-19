*** Settings ***
Documentation       Page object for the-internet.herokuapp.com /login sample page.

Resource            base_page.resource


*** Variables ***
${LOGIN_PATH}               /login
${LOGIN_USERNAME}           id=username
${LOGIN_PASSWORD}           id=password
${LOGIN_SUBMIT}             css=button[type="submit"]
${LOGIN_FLASH}              id=flash
${LOGIN_LOGOUT_BUTTON}      css=a.button.secondary.radius


*** Keywords ***
Open Login Page
    Navigate To Path    ${LOGIN_PATH}
    Page Should Be Ready
    Wait Until Element Is Visible    ${LOGIN_SUBMIT}

Login With
    [Arguments]    ${username}    ${password}
    Wait And Input    ${LOGIN_USERNAME}    ${username}
    Wait And Input    ${LOGIN_PASSWORD}    ${password}
    Wait And Click    ${LOGIN_SUBMIT}

Login Flash Should Contain
    [Arguments]    ${expected}
    Wait Until Element Is Visible    ${LOGIN_FLASH}
    Element Should Contain Text    ${LOGIN_FLASH}    ${expected}
