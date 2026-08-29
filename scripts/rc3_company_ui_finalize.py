from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    path = ROOT / 'jewel_client' / 'main.py'
    text = path.read_text('utf-8')
    old = '''        try:d=self.api.get('/api/company')
        except Exception as e:d={'settings':self.app.settings,'branch':{},'counter_count':len(self.app.counters)};self.app.error(e)
        s=d.get('settings',{});branch=d.get('branch') or {}
        fields=[('business_name','Company name',s.get('business_name','')),('branch_name','Main branch / showroom',branch.get('name','Main Showroom')),('business_state_code','GST state code',s.get('business_state_code','')),('business_state_name','State name',s.get('business_state_name','')),('business_gstin','GSTIN',s.get('business_gstin','')),('business_address','Address',s.get('business_address','')),('business_pincode','PIN code',s.get('business_pincode','')),('business_phone','Phone',s.get('business_phone','')),('business_email','Email',s.get('business_email','')),('counter_count','Number of counters',str(d.get('counter_count') or 1)),('invoice_prefix','Invoice prefix',s.get('invoice_prefix','INV')),('tag_prefix','Tag prefix',s.get('tag_prefix','TAG')),('gst_default','Default GST %',s.get('gst_default','3')),('business_timezone_offset_minutes','Timezone offset minutes',s.get('business_timezone_offset_minutes','330'))]'''
    new = '''        s=self.app.settings;branch=self.app.branches[0] if self.app.branches else {};branch_id=branch.get('id');counter_count=sum(1 for x in self.app.counters if branch_id is None or x.get('branch_id')==branch_id) or 1
        fields=[('business_name','Company name',s.get('business_name','')),('branch_name','Main branch / showroom',branch.get('name','Main Showroom')),('business_state_code','GST state code',s.get('business_state_code','')),('business_state_name','State name',s.get('business_state_name','')),('business_gstin','GSTIN',s.get('business_gstin','')),('business_address','Address',s.get('business_address','')),('business_pincode','PIN code',s.get('business_pincode','')),('business_phone','Phone',s.get('business_phone','')),('business_email','Email',s.get('business_email','')),('counter_count','Number of counters',str(counter_count)),('invoice_prefix','Invoice prefix',s.get('invoice_prefix','INV')),('tag_prefix','Tag prefix',s.get('tag_prefix','TAG')),('gst_default','Default GST %',s.get('gst_default','3')),('business_timezone_offset_minutes','Timezone offset minutes',s.get('business_timezone_offset_minutes','330'))]'''
    if old in text:
        text = text.replace(old, new, 1)
    elif new not in text:
        raise RuntimeError('Company settings UI fragment not found')
    path.write_text(text, 'utf-8')


if __name__ == '__main__':
    main()
