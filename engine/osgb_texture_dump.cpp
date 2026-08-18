// osgb_texture_dump.cpp — 读 OSGB 场景, 输出完整可采样模型
// 输出: OBJ(带 usemtl 按面分组) + MTL(map_Kd 指纹理) + 纹理 jpg 文件
// 用途: 烘焙颜色源(A 模型), Python 侧用 trimesh 加载做 ray cast 采样
// 编译: 同 build.bat (NOMINMAX + WIN32_LEAN_AND_MEAN + utf-8)
// 用法: osgb_texture_dump <input.osgb> <out_dir>
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
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
#include <vector>
#include <set>
#include <map>
#include <cstdio>

static void collectTextures(osg::StateSet* ss, std::vector<osg::ref_ptr<osg::Texture2D>>& texs,
                            std::map<osg::Image*, std::string>& imgNames, int& counter)
{
    if (!ss) return;
    for (unsigned i = 0; i < ss->getTextureAttributeList().size(); ++i) {
        osg::Texture* tex = dynamic_cast<osg::Texture*>(ss->getTextureAttribute(i, osg::StateAttribute::TEXTURE));
        if (!tex) continue;
        osg::Texture2D* t2d = dynamic_cast<osg::Texture2D*>(tex);
        if (!t2d) continue;
        osg::Image* img = t2d->getImage();
        if (!img) continue;
        if (imgNames.find(img) == imgNames.end()) {
            // 给 Image 设文件名, 让 OBJ 写入器生成 MTL 引用
            char name[64];
            snprintf(name, sizeof(name), "texture_%03d.jpg", counter++);
            img->setFileName(name);
            imgNames[img] = name;
            texs.push_back(t2d);
        }
    }
}

static void traverse(osg::Node* node, std::vector<osg::ref_ptr<osg::Texture2D>>& texs,
                     std::map<osg::Image*, std::string>& imgNames, int& counter)
{
    collectTextures(node->getStateSet(), texs, imgNames, counter);
    osg::Geode* geode = node->asGeode();
    if (geode) {
        for (unsigned i = 0; i < geode->getNumDrawables(); ++i) {
            osg::Drawable* d = geode->getDrawable(i);
            if (d) collectTextures(d->getStateSet(), texs, imgNames, counter);
        }
    }
    osg::Group* group = node->asGroup();
    if (group) {
        for (unsigned i = 0; i < group->getNumChildren(); ++i)
            traverse(group->getChild(i), texs, imgNames, counter);
    }
}

int main(int argc, char* argv[])
{
    if (argc < 3) {
        std::cerr << "Usage: osgb_texture_dump <input.osgb> <out_dir>" << std::endl;
        return 1;
    }
    std::string input = argv[1];
    std::string outDir = argv[2];

    const char* osgroot = std::getenv("OSGROOT");
    if (osgroot) {
        std::string plugDir = std::string(osgroot) + "\\bin";
        osgDB::Registry::instance()->setLibraryFilePathList(plugDir);
    }

    osg::ref_ptr<osg::Node> root = osgDB::readNodeFile(input);
    if (!root.valid()) {
        std::cerr << "Failed to read: " << input << std::endl;
        return 2;
    }

    // 1. 收集所有纹理, 设文件名
    std::vector<osg::ref_ptr<osg::Texture2D>> texs;
    std::map<osg::Image*, std::string> imgNames;
    int counter = 0;
    traverse(root.get(), texs, imgNames, counter);
    std::cout << "Found " << texs.size() << " textures" << std::endl;

    // 2. 写完整 OBJ (osgdb_obj 自动生成 MTL, usemtl 按纹理分组)
    std::string objPath = outDir + "\\model.obj";
    if (!osgDB::writeNodeFile(*root, objPath)) {
        std::cerr << "Failed to write OBJ: " << objPath << std::endl;
        return 3;
    }
    std::cout << "OBJ written: " << objPath << std::endl;

    // 3. 写所有纹理 jpg
    for (size_t i = 0; i < texs.size(); ++i) {
        osg::Image* img = texs[i]->getImage();
        if (!img) continue;
        std::string fname = imgNames[img];
        std::string path = outDir + "\\" + fname;
        if (osgDB::writeImageFile(*img, path)) {
            std::cout << "  saved " << fname << " (" << img->s() << "x" << img->t() << ")" << std::endl;
        } else {
            std::cout << "  FAILED " << fname << std::endl;
        }
    }

    std::cout << "Done. " << texs.size() << " textures, OBJ+MTL+JPG in " << outDir << std::endl;
    return 0;
}
