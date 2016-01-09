class AmiTime:
  def __init__(self, tday, tmin, tick):
    self.tday = tday
    self.tmin = tmin
    self.tick = tick

  def __str__(self):
    return "[days=%d, min=%04d, tick=%04d]" % (self.tday, self.tmin, self.tick)
  
  def to_sys_time(self):
    return (self.tick / 50) + self.tmin * 60 + self.tday * (60*60*24)

def sys_to_ami_time(t):
  ts   = int(t)         #entire seconds since epoch
  tmil = t - ts         #milliseconds
  tmin = ts / 60        #entire minutes
  ts   = ts % 60        #seconds
  tday = tmin / (60*24) #days
  tmin = tmin % (60*24) #minutes
  ts  += tmil           #seconds including milliseconds
  tick = int(ts * 50)   # 1/50 sec (tsk,tsk,tsk, no, *200 is not right here!)
  return AmiTime(tday, tmin, tick)
