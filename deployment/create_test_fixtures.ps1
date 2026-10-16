$fixtureDir = 'C:\Users\Lenovo\Documents\ChatGPT\网站\output\deployment-20261013'
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$synth.SelectVoice('Microsoft Huihui Desktop')
$synth.SetOutputToWaveFile((Join-Path $fixtureDir 'test-lesson.wav'))
$synth.Speak('这是课堂纪要功能测试。今天学习光合作用。植物利用阳光，把二氧化碳和水转化为葡萄糖，并释放氧气。这是本节课的重点。测试内容没有任何个人信息。')
$synth.Dispose()
Add-Type -AssemblyName System.Drawing
$bitmap = New-Object System.Drawing.Bitmap 1000,600
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.Clear([System.Drawing.Color]::White)
$font = New-Object System.Drawing.Font 'Microsoft YaHei',24
$brush = [System.Drawing.Brushes]::Black
$graphics.DrawString('虚构测试课表（非真实学生信息）',$font,$brush,40,35)
$graphics.DrawString('星期        时间                    课程',$font,$brush,40,140)
$graphics.DrawString('星期一    09:00 - 10:30      测试生物学',$font,$brush,40,230)
$graphics.DrawString('星期三    14:00 - 15:30      测试教育心理学',$font,$brush,40,320)
$graphics.DrawString('开学日期：2026-10-12',$font,$brush,40,450)
$bitmap.Save((Join-Path $fixtureDir 'test-timetable.png'),[System.Drawing.Imaging.ImageFormat]::Png)
$font.Dispose()
$graphics.Dispose()
$bitmap.Dispose()
