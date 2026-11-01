@echo off
chcp 65001
echo =====================================
echo 警告：即将强制覆盖远程GitHub仓库！
echo 远程仓库所有原有内容会被替换！
echo =====================================
pause

cd /d "C:\Users\Administrator\Downloads\atlas\atlas"
:: 删除旧的git信息
if exist .git (
    rmdir /s /q .git
)
echo 正在初始化Git仓库...
git init

:: 这里替换成你自己的Github用户名和邮箱！
git config user.name "bambinibazy"
git config user.email "这里换成你的github注册邮箱"

git add .
git commit -m "Full overwrite replace local atlas files"
git remote add origin https://github.com/bambinibazy/Atlas.git
git branch -M main
echo 正在强制推送(-f)到远程main分支...
git push -f origin main

echo.
echo =================完成=================
echo 如果出现401报错：需要使用Personal Access Token
echo 把链接改成：https://你的token@github.com/bambinibazy/Atlas.git
pause