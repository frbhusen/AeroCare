// Files module: translations for the reusable files panel (web/js/files/panel.js).
import { t } from "../core/index.js"; // eslint-disable-line no-unused-vars

const CATS_EN = { xray: "X-ray", photo: "Photo", medical_image: "Medical image", document: "Document", lab_report: "Lab report",
  radiology_image: "Radiology image", radiology_report: "Radiology report", branding: "Branding", other: "Other" };
const CATS_AR = { xray: "صورة شعاعية", photo: "صورة", medical_image: "صورة طبية", document: "مستند", lab_report: "تقرير مخبري",
  radiology_image: "صورة أشعة", radiology_report: "تقرير أشعة", branding: "هوية بصرية", other: "أخرى" };
const pre = (o, p) => Object.fromEntries(Object.entries(o).map(([k, v]) => [p + k, v]));

export function register(registry) {
  registry.i18n({
    en: {
      "files.title": "Files & images",
      "files.all": "All categories",
      "files.upload": "Upload",
      "files.category": "Category",
      "files.clinic": "Clinic",
      "files.description": "Description",
      "files.empty": "No files yet",
      "files.open": "Open",
      "files.download": "Download",
      "files.rename": "Rename",
      "files.rename.title": "Rename file",
      "files.name": "File name",
      "files.share": "Share",
      "files.share.title": "Share file",
      "files.share.current": "Currently shared with",
      "files.share.none": "Not shared — visible only to its clinic",
      "files.share.add": "Share with",
      "files.share.type.department": "Department",
      "files.share.type.clinic": "Clinic",
      "files.share.type.user": "Doctor",
      "files.share.revoke": "Revoke",
      "files.share.added": "File shared",
      "files.deleted": "File deleted",
      "files.storage": "Storage: {used} of {quota} used",
      "files.shared_badge": "Shared",
      ...pre(CATS_EN, "files.cat."),
    },
    ar: {
      "files.title": "الملفات والصور",
      "files.all": "كل الفئات",
      "files.upload": "رفع",
      "files.category": "الفئة",
      "files.clinic": "العيادة",
      "files.description": "الوصف",
      "files.empty": "لا توجد ملفات بعد",
      "files.open": "فتح",
      "files.download": "تنزيل",
      "files.rename": "إعادة تسمية",
      "files.rename.title": "إعادة تسمية الملف",
      "files.name": "اسم الملف",
      "files.share": "مشاركة",
      "files.share.title": "مشاركة الملف",
      "files.share.current": "مشارك حالياً مع",
      "files.share.none": "غير مشارك — مرئي لعيادته فقط",
      "files.share.add": "مشاركة مع",
      "files.share.type.department": "قسم",
      "files.share.type.clinic": "عيادة",
      "files.share.type.user": "طبيب",
      "files.share.revoke": "إلغاء المشاركة",
      "files.share.added": "تمت مشاركة الملف",
      "files.deleted": "تم حذف الملف",
      "files.storage": "التخزين: {used} من {quota} مستخدم",
      "files.shared_badge": "مشارك",
      ...pre(CATS_AR, "files.cat."),
    },
  });
}
