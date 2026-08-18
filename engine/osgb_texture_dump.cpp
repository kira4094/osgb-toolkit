// osgb_texture_dump.cpp — 读 OSGB, 提取内嵌纹理为 jpg, 导出带纹理引用的 OBJ
// 编译: 同 osgb_full (链接 osg/osgDB/osgUtil/OpenThreads, 需 osgPlugins 路径)
// 用法: osgb_texture_dump <input.osgb> <out_dir>
#include <osg/Node>
#include <osg/Geode>
#include <osg/Geometry>
#include <osg/Group>
#include <osg/Texture2D>
#include <osg/StateSet>
#include <osg/Image>
#include <osgDB/ReadFile>
#include <osgDB/WriteFile>
#include <osgDB/FileUtils>
#include <osgDB/FileNameUtils>
#include <osgDB/Registry>

#include <iostream>
#include <string>
#include <set>
#include <fstream>

// 遍历 StateSet 收集纹理
static void collectTextures(osg::StateSet* ss, std::vector<osg::ref_ptr<osg::Texture2D>>& texs,
                            std::set<osg::Image*>& seen)
{
    if (!ss) return;
    for (unsigned i = 0; i < ss->getTextureAttributeList().size(); ++i) {
        osg::Texture* tex = dynamic_cast<osg::Texture*>(ss->getTextureAttribute(i, osg::StateAttribute::TEXTURE));
        if (!tex) continue;
        osg::Texture2D* t2d = dynamic_cast<osg::Texture2D*>(tex);
        if (!t2d) continue;
        osg::Image* img = t2d->getImage();
        if (img && seen.insert(img).second) texs.push_back(t2d);
    }
}

static void traverse(osg::Node* node, std::vector<osg::ref_ptr<osg::Texture2D>>& texs,
                     std::set<osg::Image*>& seen)
{
    collectTextures(node->getStateSet(), texs, seen);
    osg::Geode* geode = node->asGeode();
    if (geode) {
        for (unsigned i = 0; i < geode->getNumDrawables(); ++i) {
            osg::Drawable* d = geode->getDrawable(i);
            if (d) collectTextures(d->getStateSet(), texs, seen);
        }
    }
    osg::Group* group = node->asGroup();
    if (group) {
        for (unsigned i = 0; i < group->getNumChildren(); ++i)
            traverse(group->getChild(i), texs, seen);
    }
}

int main(int argc, char* argv[])
{
    if (argc < 3) {
        std::cerr << "Usage: osgb_texture_dump <input.osgb> <out_dir>\n";
        return 1;
    }
    std::string input = argv[1];
    std::string outDir = argv[2];

    // 插件路径
    const char* opdir = std::getenv("OPEDITOR_DIR");
    std::string plugDir;
    if (opdir) plugDir = std::string(opdir) + "\osgPlugins-3.6.5";
    else {
        const char* osgroot = std::getenv("OSGROOT");
        if (osgroot) plugDir = std::string(osgroot) + "\bin";
    }
    if (!plugDir.empty()) {
        osgDB::Registry::instance()->setLibraryFilePathList(plugDir);
    }

    osg::ref_ptr<osg::Node> root = osgDB::readNodeFile(input);
    if (!root.valid()) {
        std::cerr << "Failed to read: " << input << std::endl;
        return 2;
    }

    // 收集纹理
    std::vector<osg::ref_ptr<osg::Texture2D>> texs;
    std::set<osg::Image*> seen;
    traverse(root.get(), texs, seen);
    std::cout << "Found " << texs.size() << " textures" << std::endl;

    // 每个纹理保存为 jpg, 记录名字映射
    for (size_t i = 0; i < texs.size(); ++i) {
        osg::Image* img = texs[i]->getImage();
        if (!img) { std::cout << "  tex " << i << ": no image" << std::endl; continue; }
        // 给 Image 设置文件名, 让 OBJ 写引用
        char name[64];
        snprintf(name, sizeof(name), "texture_%03zu.jpg", i);
        std::string path = outDir + "\\" + name;
        img->setFileName(name);  // 相对名(OBJ mtl 用)
        // 写 jpg
        if (osgDB::writeImageFile(*img, path)) {
            std::cout << "  saved " << path << " (" << img->s() << "x" << img->t() << ")" << std::endl;
        } else {
            std::cout << "  FAILED " << path << std::endl;
        }
    }

    std::cout << "Done. " << texs.size() << " textures dumped to " << outDir << std::endl;
    return 0;
}
