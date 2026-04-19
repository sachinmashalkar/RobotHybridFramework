*** Settings ***
Documentation       UI login smoke tests against the-internet.herokuapp.com.

Resource            ../../resources/common/imports.resource

Suite Setup         Log    Starting UI login suite
Test Setup          Begin Ui Test
Test Teardown       End Ui Test

Test Tags           ui    login    smoke


*** Test Cases ***
Valid Login Lands On Secure Area
    [Tags]    positive
    Open Login Page
    ${user}=    Config.Get Config Value    default_user.username
    ${pass}=    Config.Get Config Value    default_user.password
    Login With    ${user}    ${pass}
    Login Flash Should Contain    You logged into a secure area!
    Current Path Should Be    /secure

Invalid Password Is Rejected
    [Tags]    negative
    Open Login Page
    Login With    tomsmith    wrongPassword
    Login Flash Should Contain    Your password is invalid!

Unknown User Is Rejected
    [Tags]    negative
    Open Login Page
    Login With    nobody    whatever
    Login Flash Should Contain    Your username is invalid!
