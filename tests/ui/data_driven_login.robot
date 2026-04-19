*** Settings ***
Documentation       Data-driven login suite powered by robotframework-datadriver.
...                 Each row in ``testdata/login_data.csv`` becomes a test case.

Library             DataDriver    ${CURDIR}/../../testdata/login_data.csv    dialect=excel    encoding=utf_8
Resource            ../../resources/common/imports.resource

Test Setup          Begin Ui Test
Test Teardown       End Ui Test
Test Template       Attempt Login With Row

Test Tags           ui    login    data-driven


*** Test Cases ***
Login Scenario    default    default    default


*** Keywords ***
Attempt Login With Row
    [Arguments]    ${username}    ${password}    ${expected_flash}
    Open Login Page
    Login With    ${username}    ${password}
    Login Flash Should Contain    ${expected_flash}
